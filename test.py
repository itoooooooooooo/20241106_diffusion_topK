import os
os.environ["OMP_NUM_THREADS"] = "2"
import torch
import torch.nn as nn
from model import UNet, Diffuser
from data_loader import get_dataloader
from sklearn.metrics import roc_auc_score, roc_curve, auc
import yaml
import numpy as np
import matplotlib.pyplot as plt
from PIL import Image
import torchvision.transforms as transforms

def calculate_anomaly_score(original, reconstructed, k_percent=0.3):
    # ピクセルごとの絶対誤差を計算
    pixel_errors = torch.abs(original - reconstructed)
    
    # 各サンプルのピクセル誤差を1次元にフラット化
    flat_errors = pixel_errors.view(pixel_errors.size(0), -1)
    
    # トップkのピクセル誤差の合計を取得
    k = int(flat_errors.size(1) * k_percent)  # トップk％のピクセル数を計算
    topk_errors, _ = torch.topk(flat_errors, k, dim=1, largest=True)
    
    # 異常スコアを計算（スコア = 1/(F*T) * トップkの誤差合計）
    anomaly_scores = topk_errors.sum(dim=1) / (128 * 313)
    
    return anomaly_scores

# YAMLの読み込み
with open("ae.yaml", "r") as f:
    config = yaml.safe_load(f)

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

test_loader = get_dataloader(config['test_data_path'], config['batch_size'], config['n_fft'], config['hop_length'], config['n_mels'], config['power'])
model = UNet(in_ch=1).to(device)
model.load_state_dict(torch.load(config['model_directory'] + "/autoencoder_with_diffusion.pth"))
model.eval()
diffuser = Diffuser(num_timesteps=1000, device=device)

criterion = nn.MSELoss(reduction='none')

timestep = 50

results = []

with torch.no_grad():
    for data, labels in test_loader:
        data = data.to(device)
        
        # 再構成データ生成
        t = torch.full((data.size(0),), timestep, device=device, dtype=torch.long)
        x_t, noise = diffuser.add_noise(data, t)
        reconstructed = diffuser.denoise(model, x_t, t)
        
        # 異常スコアを計算してリストに追加
        scores = calculate_anomaly_score(data, reconstructed, k_percent=0.1)
        for i in range(data.size(0)):
            results.append([scores[i].item(), labels[i].item()])

# 結果の保存
results = np.array(results)
np.savetxt(config['result_directory'] + "/results.csv", results, delimiter=",", header="loss,label")

# AUC, pAUCの計算
y_true = results[:, 1]
y_scores = results[:, 0]

# AUCの計算
auc_value = roc_auc_score(y_true, y_scores)

# ROC曲線を計算
fpr, tpr, thresholds = roc_curve(y_true, y_scores)

# pAUCの計算 (0 <= FPR <= 0.1 の範囲でのAUC)
fpr_limit = 0.1  # pAUCを計算するFPRの範囲
fpr_pauc = fpr[fpr <= fpr_limit]  # FPRが0.1以下の範囲
tpr_pauc = tpr[:len(fpr_pauc)]    # 対応するTPR
pauc_value = auc(fpr_pauc, tpr_pauc) / fpr_limit  # 正規化してpAUCを0-1スケールに

# AUCとpAUCの出力
print(f"AUC: {auc_value}")
print(f"pAUC (FPR <= {fpr_limit}): {pauc_value}")


#ここからのコードは生成されたサンプルの確認用コード

# 画像を保存するディレクトリを確認し、存在しない場合は作成
result_image_directory = os.path.join(config['result_directory'], "reconstruction_comparison")
os.makedirs(result_image_directory, exist_ok=True)

# 再構成結果の比較画像を保存する関数
def save_comparison_images(original, reconstructed, label, index, reconstruction_error, result_image_directory):
    fig, axes = plt.subplots(1, 2, figsize=(10, 5))
    
    # 元のログメルスペクトログラムを表示
    axes[0].imshow(original[0].cpu().numpy(), aspect='auto', origin='lower')
    axes[0].set_title("Original Log Mel-Spectrogram")
    
    # 再構成されたログメルスペクトログラムを表示
    axes[1].imshow(reconstructed[0].cpu().numpy(), aspect='auto', origin='lower')
    axes[1].set_title("Reconstructed Log Mel-Spectrogram")

    # 再構成誤差をタイトルとして表示
    plt.suptitle(f"Label: {'Normal' if label == 0 else 'Anomaly'} | Reconstruction Error: {reconstruction_error:.4f}")
    
    # 画像の保存
    plt.savefig(os.path.join(result_image_directory, f"comparison_{index}_label_{label}.png"))
    plt.close(fig)

# 正常データと異常データを20個ずつ比較
normal_count = 0
anomaly_count = 0

with torch.no_grad():
    for data, labels in test_loader:
        data = data.to(device)

        # サンプルごとの損失を計算
        t = torch.full((data.size(0),), timestep, device=device, dtype=torch.long)
        x_t, noise = diffuser.add_noise(data, t)
        reconstructed = diffuser.denoise(model, x_t, t)

        # 再構成されたデータをクロップしてサイズを合わせる
        if reconstructed.size(3) > data.size(3):
            reconstructed = reconstructed[:, :, :, :data.size(3)]
        
        # サンプルごとの損失を計算

        scores = calculate_anomaly_score(data, reconstructed, k_percent=0.1)

        # loss = criterion(noise, noise_pred)
        
        for i in range(data.size(0)):
            # 再構成誤差を計算
            reconstruction_error = scores[i].mean().item()
            
            # 正常データと異常データを20個ずつ処理
            if labels[i].item() == 0 and normal_count < 20:
                save_comparison_images(data[i], reconstructed[i], labels[i].item(), normal_count, reconstruction_error, result_image_directory)
                normal_count += 1
            elif labels[i].item() == 1 and anomaly_count < 20:
                save_comparison_images(data[i], reconstructed[i], labels[i].item(), anomaly_count, reconstruction_error, result_image_directory)
                anomaly_count += 1
            
            # 正常データと異常データ20個ずつ処理したら終了
            if normal_count >= 20 and anomaly_count >= 20:
                break