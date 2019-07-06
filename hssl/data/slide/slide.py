from abc import abstractmethod

import torch as t
from torch.utils.data import Dataset

import numpy as np

import pandas as pd

from pyvips import Image

from scipy.ndimage.morphology import binary_fill_holes


class Slide(Dataset):
    def __init__(
            self,
            data: pd.DataFrame,
            image: Image,
            label: Image,
    ):
        self.image = image
        self.label = label
        self.data = t.tensor(data.values).float()

        self.h, self.w = self.image.height, self.image.width

        assert(self.h == self.label.height and self.w == self.label.width)

    @abstractmethod
    def _get_patch(self, idx: int):
        pass

    @abstractmethod
    def __len__(self):
        pass

    def __getitem__(self, idx):
        image, label = self._get_patch(idx)

        # remove partially visible labels
        label[np.invert(binary_fill_holes(label == 0))] = 0

        labels = [*sorted(np.unique(label))]
        data = self.data[[x - 1 for x in labels if x > 0], :]
        if len(data) == 0:
            return self.__getitem__((idx + 1) % len(self))
        label = np.searchsorted(labels, label)

        return dict(
            image=t.tensor(image / 255 * 2 - 1).permute(2, 0, 1).float(),
            label=t.tensor(label).long(),
            data=data,
            type='ST',
        )