import os
os.environ["OMP_NUM_THREADS"] = "2"
import torch
import librosa
import numpy as np

import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader

class AudioDataset(Dataset):
    def __init__(self, data_path, n_fft, hop_length, n_mels, power):
        self.data_path = data_path
        self.files = [f for f in os.listdir(data_path) if f.endswith(".wav")]
        self.n_fft = n_fft
        self.hop_length = hop_length
        self.n_mels = n_mels
        self.power = power

    def __len__(self):
        return len(self.files)

    def __getitem__(self, idx):
        file_name = os.path.join(self.data_path, self.files[idx])
        y, sr = librosa.load(file_name, sr=None)
        mel_spectrogram = librosa.feature.melspectrogram(y=y, sr=sr, n_fft=self.n_fft, 
                                                         hop_length=self.hop_length, 
                                                         n_mels=self.n_mels, 
                                                         power=self.power)
        log_mel_spectrogram = 20.0 / self.power * np.log10(mel_spectrogram + np.finfo(float).eps)
        log_mel_spectrogram = torch.tensor(log_mel_spectrogram).unsqueeze(0)  # Conv2D用にチャンネル追加

        # サイズを (128, 312) にリサイズ ->313だと再構成データの形が１ずれたため
        log_mel_spectrogram = F.interpolate(log_mel_spectrogram.unsqueeze(0), size=(128, 312), mode='bilinear', align_corners=False).squeeze(0)

        # 正規化処理 (0, 1) の範囲にスケール
        log_mel_spectrogram_min = log_mel_spectrogram.min()
        log_mel_spectrogram_max = log_mel_spectrogram.max()
        log_mel_spectrogram = (log_mel_spectrogram - log_mel_spectrogram_min) / (log_mel_spectrogram_max - log_mel_spectrogram_min + 1e-8)

        label = 0 if "normal" in file_name else 1
        return log_mel_spectrogram, label

def get_dataloader(data_path, batch_size, n_fft, hop_length, n_mels, power):
    dataset = AudioDataset(data_path, n_fft, hop_length, n_mels, power)
    dataloader = DataLoader(dataset, batch_size=batch_size, shuffle=True)
    return dataloader
