import math

import torch
from torch import nn
from torch.autograd import Variable
# from .utils import load_state_dict_from_url

# model_urls = {
#     'efficientnet_b0': 'https://www.dropbox.com/s/9wigibun8n260qm/efficientnet-b0-4cfa50.pth?dl=1',
#     'efficientnet_b1': 'https://www.dropbox.com/s/6745ear79b1ltkh/efficientnet-b1-ef6aa7.pth?dl=1',
#     'efficientnet_b2': 'https://www.dropbox.com/s/0dhtv1t5wkjg0iy/efficientnet-b2-7c98aa.pth?dl=1',
#     'efficientnet_b3': 'https://www.dropbox.com/s/5uqok5gd33fom5p/efficientnet-b3-bdc7f4.pth?dl=1',
#     'efficientnet_b4': 'https://www.dropbox.com/s/y2nqt750lixs8kc/efficientnet-b4-3e4967.pth?dl=1',
#     'efficientnet_b5': 'https://www.dropbox.com/s/qxonlu3q02v9i47/efficientnet-b5-4c7978.pth?dl=1',
#     'efficientnet_b6': None,
#     'efficientnet_b7': None,
# }

params = {
    'efficientnet_b0': (1.0, 1.0, 224, 0.2),
    'efficientnet_b1': (1.0, 1.1, 240, 0.2),
    'efficientnet_b2': (1.1, 1.2, 260, 0.3),
    'efficientnet_b3': (1.2, 1.4, 300, 0.3),
    'efficientnet_b4': (1.4, 1.8, 380, 0.4),
    'efficientnet_b5': (1.6, 2.2, 456, 0.4),
    'efficientnet_b6': (1.8, 2.6, 528, 0.5),
    'efficientnet_b7': (2.0, 3.1, 600, 0.5),
}


class Swish(nn.Module):

    def __init__(self, *args, **kwargs):
        super(Swish, self).__init__()

    def forward(self, x):
        return x * torch.sigmoid(x)


class ConvBNReLU(nn.Sequential):

    def __init__(self, in_planes, out_planes, kernel_size, stride=1, groups=1):
        padding = self._get_padding(kernel_size, stride)
        super(ConvBNReLU, self).__init__(
            nn.ZeroPad2d(padding),
            nn.Conv2d(in_planes, out_planes, kernel_size, stride, padding=0, groups=groups, bias=False),
            nn.BatchNorm2d(out_planes, eps=1e-5, momentum=0.01),
            Swish(),
        )

    def _get_padding(self, kernel_size, stride):
        p = max(kernel_size - stride, 0)
        return [p // 2, p - p // 2, p // 2, p - p // 2]


class SqueezeExcitation(nn.Module):

    def __init__(self, in_planes, reduced_dim):
        super(SqueezeExcitation, self).__init__()
        self.se = nn.Sequential(
            nn.AdaptiveAvgPool2d(1),
            nn.Conv2d(in_planes, reduced_dim, 1, bias=True),
            Swish(),
            nn.Conv2d(reduced_dim, in_planes, 1, bias=True),
            nn.Sigmoid(),
        )

    def forward(self, x):
        return x * self.se(x)


class MBConvBlock(nn.Module):

    def __init__(self,
                 in_planes,
                 out_planes,
                 expand_ratio,
                 kernel_size,
                 stride,
                 reduction_ratio=4,
                 drop_connect_rate=0.2):
        super(MBConvBlock, self).__init__()
        self.drop_connect_rate = drop_connect_rate
        self.use_residual = (in_planes == out_planes and stride == 1)
        assert stride in [1, 2]
        assert kernel_size in [3, 5]

        hidden_dim = in_planes * expand_ratio
        reduced_dim = max(1, int(in_planes / reduction_ratio))

        layers = []
        # pw
        if in_planes != hidden_dim:
            layers += [ConvBNReLU(in_planes, hidden_dim, 1)]

        layers += [
            # dw
            ConvBNReLU(hidden_dim, hidden_dim, kernel_size, stride=stride, groups=hidden_dim),
            # se
            SqueezeExcitation(hidden_dim, reduced_dim),
            # pw-linear
            nn.Conv2d(hidden_dim, out_planes, 1),
            nn.BatchNorm2d(out_planes, eps=1e-5, momentum=0.01),
        ]

        self.conv = nn.Sequential(*layers)

    def _drop_connect(self, x):
        if not self.training:
            return x
        keep_prob = 1.0 - self.drop_connect_rate
        batch_size = x.size(0)
        random_tensor = keep_prob
        random_tensor += torch.rand((batch_size, 1, 1, 1), dtype=x.dtype, device=x.device)
        binary_tensor = random_tensor.floor()
        return x.div(keep_prob) * binary_tensor

    def forward(self, x):
        if self.use_residual:
            return x + self._drop_connect(self.conv(x))
        else:
            return self.conv(x)


def _make_divisible(value, divisor=8):
    new_value = max(divisor, int(value + divisor / 2) // divisor * divisor)
    if new_value < 0.9 * value:
        new_value += divisor
    return new_value


def _round_filters(filters, width_mult):
    if width_mult == 1.0:
        return filters
    return int(_make_divisible(filters * width_mult))


def _round_repeats(repeats, depth_mult):
    if depth_mult == 1.0:
        return repeats
    return int(math.ceil(depth_mult * repeats))

####### arcloss ##############
def where(cond, x_1, x_2):
    return (cond * x_1) + ((1 - cond) * x_2)

def l2_norm(input,axis=1):
    norm = torch.norm(input,2,axis,True)
    output = torch.div(input, norm)
    return output

class L2norm(nn.Module):
    def __init__(self, axis=1):
        super(L2norm, self).__init__()
        self.axis = axis
    def forward(self, input,):
        norm = torch.norm(input,2, self.axis,True)
        output = torch.div(input, norm)
        return output

class Arcface(nn.Module):
    # implementation of additive margin softmax loss in https://arxiv.org/abs/1801.05599    
    def __init__(self, embedding_size=200, classnum=100):
        super(Arcface, self).__init__()
        self.classnum = classnum
        self.kernel = nn.Parameter(torch.Tensor(embedding_size,classnum))
        # initial kernel
        self.kernel.data.uniform_(-1, 1).renorm_(2,1,1e-5).mul_(1e5)
    def forward(self, embbedings):
        # weights norm
        nB = len(embbedings)
        kernel_norm = l2_norm(self.kernel, axis=0)
        # cos(theta+m)
        cos_theta = torch.mm(embbedings,kernel_norm)
#         output = torch.mm(embbedings,kernel_norm)
        cos_theta = cos_theta.clamp(-1,1) # for numerical stability
        # print(cos_theta)
        return cos_theta

def Arctransf(feat, s=5.):
    output = feat*1.0
    output *= s    
    return output

class Margloss(nn.Module):
    # implementation of additive margin softmax loss in https://arxiv.org/abs/1801.05599    
    def __init__(self,  s=5.):
        super(Margloss, self).__init__()
        self.s = s # scalar value default is 64, see normface https://arxiv.org/abs/1704.06369
    def forward(self, feat, label):
        nB = len(feat)
        output = feat * 1.0 # a little bit hacky way to prevent in_place operation on cos_theta
        output *= self.s # scale up in order to make softmax work, first introduced in normface
        loss = nn.CrossEntropyLoss()
        out = loss(output, label)
        return out   # return out--loss

class Arcloss(nn.Module):
    # implementation of additive margin softmax loss in https://arxiv.org/abs/1801.05599    
    def __init__(self,  s=5., m=0.0):
        super(Arcloss, self).__init__()
        self.m = m # the margin value, default is 0.5
        self.s = s # scalar value default is 64, see normface https://arxiv.org/abs/1704.06369
        self.cos_m = math.cos(m)
        self.sin_m = math.sin(m)
        self.mm = self.sin_m * m  # issue 1
        self.threshold = math.cos(math.pi - m)
    def forward(self, feat, label):
        # print(label)
        nB = len(feat)
        cos_theta_2 = torch.pow(feat, 2)
        sin_theta_2 = 1 - cos_theta_2
        sin_theta = torch.sqrt(sin_theta_2)
        cos_theta_m = (feat * self.cos_m - sin_theta * self.sin_m)
        # this condition controls the theta+m should in range [0, pi]
        #      0<=theta+m<=pi
        #     -m<=theta<=pi-m
        cond_v = feat - self.threshold
        # print(cond_v)
        cond_mask = cond_v <= 0
        keep_val = (feat - self.mm) # when theta not in [0,pi], use cosface instead
        cos_theta_m[cond_mask] = keep_val[cond_mask]
        output = feat * 1.0 # a little bit hacky way to prevent in_place operation on cos_theta
        idx_ = torch.arange(0, nB, dtype=torch.long)
        output[idx_, label] = cos_theta_m[idx_, label]
        output *= self.s # scale up in order to make softmax work, first introduced in normface
        # print(output)
        loss = nn.CrossEntropyLoss()
        out = loss(output, label)
        return out   # return out--loss

class CosLoss(nn.Module):
    def __init__(self, num_cls=100, s=5, alpha=0.1):
        super(CosLoss, self).__init__()
        self.num_cls = num_cls
        self.alpha = alpha
        self.scale = s
        self.phi=nn.Parameter(torch.Tensor(1))
        self.phi.data.uniform_(s, -s)

    def forward(self, feat, y):
        y = y.view(-1, 1)
        batch_size = feat.size()[0]
        feat = feat + self.phi.expand_as(feat)
        margin_xw_norm = feat - self.alpha
        y_onehot = torch.Tensor(batch_size, self.num_cls).cuda()
        y_onehot.zero_()
        y_onehot.scatter_(1, y.data.view(-1, 1), 1)
        y_onehot.byte()
        y_onehot = Variable(y_onehot, requires_grad=False)
        value = self.scale * where(y_onehot, margin_xw_norm, feat)
        # value = value
        # logpt = F.log_softmax(value)
        y = y.view(-1)
        loss = nn.CrossEntropyLoss()
        output = loss(value, y)
        # loss = loss.mean()
        return output

class mCosLoss(nn.Module):
    def __init__(self, num_cls=100, s=2, alpha=0.1):
        super(mCosLoss, self).__init__()
        self.num_cls = num_cls
        self.alpha = alpha
        self.scale = s
        self.phi=nn.Parameter(torch.Tensor(1))
        self.phi.data.uniform_(s, -s)###

    def forward(self, feat, y):
        y = y.view(-1, 1)
        batch_size = feat.size()[0]
        feat = feat + self.phi.expand_as(feat)
        margin_xw_norm_h = feat - self.alpha 
        margin_xw_norm_l = feat + self.alpha
        y_onehot = torch.Tensor(batch_size, self.num_cls).cuda()
        y_onehot.zero_()
        y_onehot.scatter_(1, y.data.view(-1, 1), 1)
        y_onehot.byte()
        y_onehot = Variable(y_onehot, requires_grad=False)
        value = self.scale * where(y_onehot, margin_xw_norm_h, margin_xw_norm_l)
        # value = value
        # logpt = F.log_softmax(value)
        y = y.view(-1)
        loss = nn.CrossEntropyLoss()
        output = loss(value, y)
        # loss = loss.mean()
        return output
###############################

class EfficientNet(nn.Module):

    # LR_REGIME = [1, 25, 0.05, 26, 40, 0.005, 41, 50, 0.0005, 51, 55, 0.00005]

    LR_REGIME = [1, 25, 0.07, 26, 50, 0.007, 51, 65, 0.0007, 66, 70, 0.00007]

    def __init__(self, width_mult=1.0, depth_mult=1.0, dropout_rate=0.2, num_classes=100, coslinear=False):
        super(EfficientNet, self).__init__()

        # yapf: disable
        settings = [
            # t,  c, n, s, k
            # [1,  16, 1, 1, 3],  # MBConv1_3x3, SE, 112 -> 112
            # [6,  24, 2, 2, 3],  # MBConv6_3x3, SE, 112 ->  56
            # [6,  40, 2, 2, 5],  # MBConv6_5x5, SE,  56 ->  28   
            # [6,  80, 3, 2, 3],  # MBConv6_3x3, SE,  28 ->  14   
            # [6, 112, 3, 1, 5],  # MBConv6_5x5, SE,  14 ->  14
            # [6, 192, 4, 2, 5],  # MBConv6_5x5, SE,  14 ->   7  
            # [6, 320, 1, 1, 3]   # MBConv6_3x3, SE,   7 ->   7

            #####
            # for size 32 test 1
            # [1,  16, 1, 1, 3],  # MBConv1_3x3, SE,  16 ->  16
            # [6,  24, 2, 2, 3],  # MBConv6_3x3, SE,  16 ->   8   
            # [6,  40, 2, 1, 5],  # MBConv6_5x5, SE,   8 ->   8   
            # [6,  80, 3, 1, 3],  # MBConv6_3x3, SE,   8 ->   8  
            # [6, 112, 3, 1, 5],  # MBConv6_5x5, SE,   8 ->   8  
            # [6, 192, 4, 1, 5],  # MBConv6_5x5, SE,   8 ->   8   
            # [6, 320, 1, 1, 3]   # MBConv6_3x3, SE,   8 ->   8
            # for size 32 test 2
            [1,  16, 1, 1, 3],  # MBConv1_3x3, SE,  32 ->  32
            [6,  24, 2, 1, 3],  # MBConv6_3x3, SE,  32 ->  32   
            [6,  40, 2, 2, 5],  # MBConv6_5x5, SE,  32 ->  16   
            [6,  80, 3, 1, 3],  # MBConv6_3x3, SE,  16 ->  16 
            # [6, 112, 3, 1, 5],  # MBConv6_5x5, SE,  16 ->   8   16->16
            # [6, 192, 4, 2, 5],  # MBConv6_5x5, SE,   8 ->   8   16->8
            # [6, 320, 1, 1, 3]   # MBConv6_3x3, SE,   8 ->   8   8->8  
            ####

        ]
        ###########################################  
        settings_2 = [
            [6, 112, 3, 1, 5],  # MBConv6_5x5, SE,  16 ->   8   16->16
            [6, 192, 4, 2, 5],  # MBConv6_5x5, SE,   8 ->   8   16->8
            [6, 320, 1, 1, 3]   # MBConv6_3x3, SE,   8 ->   8   8->8
        ]
        # yapf: enable

        out_channels = _round_filters(32, width_mult)

        # test 1 or size 224
        # features = [ConvBNReLU(3, out_channels, 3, stride=2)]

        # for size 32 ## test 2
        features = [ConvBNReLU(3, out_channels, 3, stride=1)]
        ##### 

        in_channels = out_channels
        for t, c, n, s, k in settings:
            out_channels = _round_filters(c, width_mult)
            repeats = _round_repeats(n, depth_mult)
            for i in range(repeats):
                stride = s if i == 0 else 1
                features += [MBConvBlock(in_channels, out_channels, expand_ratio=t, stride=stride, kernel_size=k)]
                in_channels = out_channels
      
        features_2 = [] ######
        for t, c, n, s, k in settings_2:
            out_channels = _round_filters(c, width_mult)
            repeats = _round_repeats(n, depth_mult)
            for i in range(repeats):
                stride = s if i == 0 else 1
                features_2 += [MBConvBlock(in_channels, out_channels, expand_ratio=t, stride=stride, kernel_size=k)]
                in_channels = out_channels
        #########################################
        # remove 1280 layer
        last_channels = _round_filters(1280, width_mult)
        # features += [ConvBNReLU(in_channels, last_channels, 1)]
        features_2 += [ConvBNReLU(in_channels, last_channels, 1)]
        # last_channels = in_channels

        # replace Avepooling -> Conv
        # self.Conv_last = nn.Conv2d(last_channels,last_channels, 8, groups = last_channels, bias=False)

        self.features = nn.Sequential(*features)
        self.features_2 = nn.Sequential(*features_2)
        if coslinear:
            print('using coslinear')
            mid_channels = 200
            self.classifier = nn.Sequential(
                # nn.Dropout(dropout_rate),
                nn.Linear(last_channels, mid_channels),
                L2norm(),
                # nn.Dropout(dropout_rate),
                Arcface(mid_channels, num_classes),
            )
        else:
            print('using Linear')
            self.classifier = nn.Sequential(
                nn.Dropout(dropout_rate),
                nn.Linear(last_channels, num_classes),
            )


        for m in self.modules():
            # if isinstance(m, nn.Conv2d):
            #     nn.init.kaiming_normal_(m.weight, mode='fan_out', nonlinearity='relu')
            # elif isinstance(m, nn.BatchNorm2d):
            #     m.weight.data.fill_(1.0)
            #     m.bias.data.zero_()
            # elif isinstance(m, nn.Linear):
            #     nn.init.kaiming_uniform_(m.weight, mode='fan_in', nonlinearity='linear')

            if isinstance(m, nn.Conv2d):
                n = m.kernel_size[0] * m.kernel_size[1] * m.out_channels  # fan-out
                m.weight.data.normal_(0, math.sqrt(2.0 / n))
                if m.bias is not None:
                    m.bias.data.zero_()
            elif isinstance(m, nn.BatchNorm2d):
                m.weight.data.fill_(1.0)
                m.bias.data.zero_()
            elif isinstance(m, nn.Linear):
                n = m.weight.size(0)  # fan-out
                init_range = 1.0 / math.sqrt(n)
                m.weight.data.uniform_(-init_range, init_range)
                m.bias.data.zero_()

    def forward(self, x):
        x = self.features(x)
        # print(x.size())
        ######
        out1 = x
        x = self.features_2(x)
        ######
        # x = self.Conv_last(x).view(-1,1536)
        # print(x.size())
        x = x.mean(2).mean(2)
        # x = torch.mean(x,dim=[2,3])
        # print(x.size())
        x = self.classifier(x)
        return x, out1


def _efficientnet(arch, pretrained, progress, **kwargs):
    width_mult, depth_mult, _, dropout_rate = params[arch]
    model = EfficientNet(width_mult, depth_mult, dropout_rate, **kwargs)
    if pretrained:
        state_dict = load_state_dict_from_url(model_urls[arch], progress=progress)

        if 'num_classes' in kwargs and kwargs['num_classes'] != 1000:
            del state_dict['classifier.1.weight']
            del state_dict['classifier.1.bias']

        model.load_state_dict(state_dict, strict=False)
    return model


def efficientnet_b0(pretrained=False, progress=True, **kwargs):
    return _efficientnet('efficientnet_b0', pretrained, progress, **kwargs)


def efficientnet_b1(pretrained=False, progress=True, **kwargs):
    return _efficientnet('efficientnet_b1', pretrained, progress, **kwargs)


def efficientnet_b2(pretrained=False, progress=True, **kwargs):
    return _efficientnet('efficientnet_b2', pretrained, progress, **kwargs)


def efficientnet_b3(pretrained=False, progress=True, **kwargs):
    return _efficientnet('efficientnet_b3', pretrained, progress, **kwargs)


def efficientnet_b4(pretrained=False, progress=True, **kwargs):
    return _efficientnet('efficientnet_b4', pretrained, progress, **kwargs)


def efficientnet_b5(pretrained=False, progress=True, **kwargs):
    return _efficientnet('efficientnet_b5', pretrained, progress, **kwargs)


def efficientnet_b6(pretrained=False, progress=True, **kwargs):
    return _efficientnet('efficientnet_b6', pretrained, progress, **kwargs)


def efficientnet_b7(pretrained=False, progress=True, **kwargs):
    return _efficientnet('efficientnet_b7', pretrained, progress, **kwargs)
