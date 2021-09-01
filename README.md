### FA_Distillation EfficientNet-ex(x) with Angleloss and Label Refinery*

Based on MicroNet-CIFAR100: *EfficientNet-ex(x) with Angleloss and Label Refinery*(https://github.com/madokaminami/UCI-CIFAR100)
By [Biao Yang] biaoy1@uci.edu,
[Fanghui Xue] fanghuix@uci.edu,
[Jiancheng Lyu] jianlyu@qti.qualcomm.com,
[Shuai Zhang] shuazhan@qti.qualcomm.com,
[Yingyong Qi] yingyong@qti.qualcomm.com,
and [Jack xin] jack.xin@uci.edu


### 1. Introduction
This is a pytorch training script for light weight network on CIFAR-100. We aim to participate in the MicroNet Chanllenge hosted at NeurIPS 2019. Our solution is based on label refinery (https://arxiv.org/abs/1805.02641), EfficientNet (https://arxiv.org/pdf/1905.11946.pdf) and additive margin softmax loss (https://arxiv.org/pdf/1801.05599.pdf).

We propose two models, EfficientNet-ex and EfficientNet-exx, both adapted from EfficientNet. We modified the models to meet the input size of 32x32 and replaced the cross-entropy with additive margin softmax loss with s=5.0 and m=0.0. We also enlarged our dataset with different transformations of the original CIFAR-100, without using any external data.


### 2. Usage
#### Prerequisite
Python3.5+ is required. Other requirements can be found in [requirements.txt](requirements.txt).
To install the packages:
```
pip3 install -r requirements.txt
```

#### Train models
Before running the code, make sure the data has been downloaded.

Fisrt, train EfficientNet-B3 with default parameters and save the model with the highest test accuracy. Usually the model can achieve test accuracy above 79%.
Next, retrain the EfficientNet-B3 with the refined labels of the saved model. After the second training of EfficientNet-B3, it can achieve accuracy above 80%.
Then train EfficientNet-B0 with the refined labels of EfficientNet-B3.
The FA loss is already included during the training, you may need to comment it if a orginal training process is needed.

Some basic settings: 
batch size: 128, number of epochs: 70, learning rate: (1-25: 0.07, 26-50: 0.007, 51-65: 0.0007, 66-70: 0.00007), GPU: two GTX 1080 Ti GPUs.

1. Train EfficientNet-B3:
```
python train.py --model efficientnet_b3 --data_dir (path to you data) --s (default 5.0) --coslinear True
```
2. Train EfficientNet-B3 with refined labels:
```
python train.py --model efficientnet_b3 --label-refinery-model efficientnet_b3 --label-refinery-state-file (path to best model_state.pytar) --s (default 5.0) --coslinear True
```
3. Train EfficientNet-B0 with refined labels of EfficientNet-B3:
```
python train.py --model efficientnet_b0 --label-refinery-model efficientnet_b3 --label-refinery-state-file (path to best model_state.pytar) --s (default 5.0) --coslinear True
```


#### Test models
To test a trained EfficientNet-ex model:
```
python test.py --model efficientnet_ex --model-state-file (path to best model.pytar) --data_dir (path to you data)
```
And to test a trained EfficientNet-exx model:
```
python test.py --model efficientnet_exx --model-state-file (path to best model.pytar) --data_dir (path to you data)
```

#### Print number of operations and parameters
```
python ./torchscope-master/count.py
```
*Specify the "mul_factor" in the line 83 of "scope.py" to determine whether multiplication is counted as 1/2 or 1 operation:
madds = compute_madd(module, input[0], output, mul_factor = 0.5)

### 3. Parameter and Operation Details
#### EfficientNet-ex model:

FA loss experiments:
We test FA loss on EfficientNet on Cifar-100 dataset. We first train EfficientNet-B3. Then we use EfficientNet-B3 to help training a smaller network EfficientNet-B0 with/without FA loss. Here as the task is different from that in \cite{wang2020dual}, we do not add extra 1x1 Conv before implementing the FA loss. The FA loss is adding before the MBConvBlock with out channel number of 112. And to make sure the feature maps having the same size, we let EfficientNet-B3's feature map downsample to the same size as  EfficientNet-B0's.

Comparison of adding FA loss. B3 as teacher, B0 as student

|  Models | accuracy  | accuracy  | acc at 1st/2nd epoch  |Pa/Fl |
|  ----  | ----  |  ----  |----  |----  |
| B3   | 72.59 | 80.54(refined)   |- |10.5M/0.97G  |
| B0  | 73.19 |76.16  |9.29/16.15  |4.1M/0.38G |
| B0 with FA   | 73.45 | 78.18   |23.58/40.00  |4.1M/0.38G |
### 4. License
By downloading this software you acknowledge that you read and agreed all the
terms in the `LICENSE` file.

Sep 1st, 2021
