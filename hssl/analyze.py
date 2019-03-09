import os

from imageio import imwrite

from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.pyplot as plt

import numpy as np

import torch as t

from torchvision.utils import make_grid

from .network import Histonet
from .logging import WARNING, log


def run_tsne(y, n_components=3, initial_dims=20):
    from sklearn.decomposition import PCA
    from sklearn.manifold import TSNE
    x = y.reshape(-1, y.shape[-1])

    def uniformize(x):
        return (x - x.min(0)) / (x.max(0) - x.min(0))

    print("performing PCA")
    pca_map = PCA(n_components=initial_dims).fit_transform(x)
    print("performing tSNE")
    tsne_map = (
        TSNE(n_components=n_components, verbose=1)
        .fit_transform(pca_map)
    )
    tsne_map = uniformize(tsne_map)
    return tsne_map.reshape((*y.shape[:2], -1))


def visualize(model, z):
    import matplotlib.pyplot as plt
    nmu, nsd, *_ = model.decode(z)
    return plt.imshow(nmu[0].detach().numpy().transpose(1, 2, 0))


def interpolate(model, z1, z2, to='/tmp/interpolation.mp4'):
    from matplotlib.animation import ArtistAnimation
    fig = plt.figure()
    anim = ArtistAnimation(
        fig,
        [
            [visualize(model, z1 + (z2 - z1) * k)]
            for k in np.linspace(0, 1, 100)
        ],
        repeat_delay=1000,
        interval=50,
        blit=True,
    )
    anim.save(to)


def side_by_side(x, y):
    import matplotlib.pyplot as plt
    from sklearn.decomposition import PCA
    plt.subplot(1, 2, 1)
    plt.imshow(x['image'][0].permute(1, 2, 0).detach())
    plt.subplot(1, 2, 2)
    pca = (
        PCA(n_components=3)
        .fit_transform(y[0].reshape(y.shape[1], -1).t().detach())
        .reshape(*y.shape[-2:], -1)
    )
    _min, _max = np.quantile(pca, [0.1, 0.9])
    pca = pca.clip(_min, _max)
    plt.imshow((pca - _min) / (_max - _min))
    plt.show()


def clip(x, q):
    if isinstance(q, float):
        minq, maxq = q, 1 - q
    else:
        try:
            minq, maxq = q
        except TypeError:
            raise ValueError('`q` mus be float or iterable')
    return np.clip(x, *np.quantile(x, [minq, maxq]))


def normalize(x):
    _min = x.min((0, 2, 3))[..., None, None]
    _max = x.max((0, 2, 3))[..., None, None]
    return (x - _min) / (_max - _min)


def dim_red(x, method='pca', n_components=3, **kwargs):
    if method != 'pca':
        raise NotImplementedError()

    from sklearn.decomposition import PCA

    if isinstance(x, t.Tensor):
        x = x.detach().cpu().numpy()

    return normalize(clip(
        (
            PCA(n_components=n_components, **kwargs)
            .fit_transform(
                x
                .transpose(0, 2, 3, 1)
                .reshape(-1, x.shape[1])
            )
            .reshape(x.shape[0], *x.shape[2:], n_components)
            .transpose(0, 3, 1, 2)
        ),
        0.01,
    ))


def visualize_batch(batch, normalize=False, **kwargs):
    if isinstance(batch, t.Tensor):
        batch = batch.detach().cpu()
    else:
        batch = t.as_tensor(batch)
    return np.transpose(
        (
            make_grid(
                batch,
                nrow=int(np.floor(np.sqrt(len(batch)))),
                padding=int(np.ceil(np.sqrt(
                    np.product(batch.shape[-2:])) / 100)),
                normalize=normalize,
            )
            .detach()
            .cpu()
            .numpy()
        ),
        (1, 2, 0),
    )


def analyze(
        histonet: Histonet,
        image,
        data=None,
        label=None,
        output_prefix=None,
        device=None,
):
    if data is not None or label is not None:
        log(
            WARNING,
            'arguments `data` and `label` are currently not supported'
            ' and will be ignored'
        )

    if output_prefix is None:
        output_prefix = '.'

    if device is None:
        device = t.device('cpu')

    histonet = histonet.to(device)

    genes = histonet.init_args['num_genes']

    z, mu, sd, rate, logit, state = histonet(
        t.cat(
            [
                image[None, ...],
                t.cat(
                    [
                        t.ones((1, 1, *image.shape[-2:])),
                        t.zeros((1, genes, *image.shape[-2:])),
                    ],
                    dim=1,
                )
            ],
            dim=1,
        ),
    )

    xpr = rate * t.exp(logit.t()[..., None, None])
    xpr_rel = xpr / xpr.sum(1).unsqueeze(1)

    for b, prefix in [
            (
                (
                    t.distributions.Normal(mu, sd)
                    .sample()
                    .clamp(0, 1)
                ),
                'he',
            ),
            (dim_red(z), 'z'),
            (dim_red(xpr), 'xpr'),
            (dim_red(xpr_rel), 'xpr-rel'),
            (dim_red(state), 'state'),
    ]:
        imwrite(
            os.path.join(output_prefix, f'{prefix}.png'),
            visualize_batch(b),
        )

    for d, postfix in [
            (xpr    [0].detach().cpu().numpy()[::-1], 'abs'),
            (xpr_rel[0].detach().cpu().numpy()[::-1], 'rel'),
    ]:
        with PdfPages(os.path.join(
                output_prefix, f'genes-{postfix}.pdf')) as pdf:
            for p, g in zip(d, data.columns[::-1]):
                plt.figure()
                plt.imshow(clip(p, 0.01))
                plt.title(g)
                pdf.savefig()
                plt.close()