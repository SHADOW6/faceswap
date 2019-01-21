#!/usr/bin/env python3
""" Neural Network Blocks for faceswap.py
    Blocks from:
        the original https://www.reddit.com/r/deepfakes/ code sample + contribs
        dfaker: https://github.com/dfaker/df
        shoanlu GAN: https://github.com/shaoanlu/faceswap-GAN"""

import tensorflow as tf
import keras.backend as K

from keras.layers import (add, Add, BatchNormalization, concatenate, Lambda, regularizers,
                          Permute, Reshape, SeparableConv2D, Softmax, UpSampling2D)
from keras.layers.advanced_activations import LeakyReLU
from keras.layers.convolutional import Conv2D
from keras.layers.core import Activation
from keras.initializers import he_uniform
from .layers import PixelShuffler, Scale, SubPixelUpscaling
from .normalization import GroupNormalization, InstanceNormalization


# <<< Original Model Blocks >>> #

def conv(inp, filters, kernel_size=5, strides=2, use_instance_norm=False, **kwargs):
    """ Convolution Layer"""
    kwargs["kernel_initializer"] = kwargs.get("kernel_initializer", he_uniform())
    print(kwargs)
    var_x = Conv2D(filters,
                   kernel_size=kernel_size,
                   strides=strides,
                   padding='same',
                   **kwargs)(inp)
    if use_instance_norm:
        var_x = InstanceNormalization()(var_x)
    var_x = LeakyReLU(0.1)(var_x)
    return var_x


def upscale(inp, filters, kernel_size=3, use_instance_norm=False, use_subpixel=False, **kwargs):
    """ Upscale Layer """
    kwargs["kernel_initializer"] = kwargs.get("kernel_initializer", he_uniform())
    var_x = Conv2D(filters * 4,
                   kernel_size=kernel_size,
                   padding='same',
                   **kwargs)(inp)
    if use_instance_norm:
        var_x = InstanceNormalization()(var_x)
    var_x = LeakyReLU(0.1)(var_x)
    if use_subpixel:
        var_x = SubPixelUpscaling()(var_x)
    else:
        var_x = PixelShuffler()(var_x)
    return var_x


# <<< DFaker Model Blocks >>> #

def res_block(inp, filters, kernel_size=3, **kwargs):
    """ Residual block """
    kwargs["kernel_initializer"] = kwargs.get("kernel_initializer", he_uniform())
    var_x = inp
    var_x = Conv2D(filters,
                   kernel_size=kernel_size,
                   use_bias=False,
                   padding="same",
                   **kwargs)(var_x)
    var_x = LeakyReLU(alpha=0.2)(var_x)
    var_x = Conv2D(filters,
                   kernel_size=kernel_size,
                   use_bias=False,
                   padding="same",
                   **kwargs)(var_x)
    var_x = Add()([var_x, inp])
    var_x = LeakyReLU(alpha=0.2)(var_x)
    return var_x


# <<< OriginalHiRes Blocks >>> #

def conv_sep(inp, filters, kernel_size=5, strides=2, **kwargs):
    """ Seperable Convolution Layer """
    kwargs["kernel_initializer"] = kwargs.get("kernel_initializer", he_uniform())
    var_x = SeparableConv2D(filters,
                            kernel_size=kernel_size,
                            strides=strides,
                            padding='same',
                            **kwargs)(inp)
    var_x = Activation("relu")(var_x)
    return var_x

# <<< GAN V2.2 Blocks >>> #


# Gan Constansts:
GAN22_CONV_INIT = "he_normal"
GAN22_REGULARIZER = 1e-4


# Gan Blocks:
def normalization(inp, norm='none', group='16'):
    """ GAN Normalization """
    if norm == 'layernorm':
        var_x = GroupNormalization(group=group)(inp)
    elif norm == 'batchnorm':
        var_x = BatchNormalization()(inp)
    elif norm == 'groupnorm':
        var_x = GroupNormalization(group=16)(inp)
    elif norm == 'instancenorm':
        var_x = InstanceNormalization()(inp)
    elif norm == 'hybrid':
        if group % 2 == 1:
            raise ValueError("Output channels must be an even number for hybrid norm, "
                             "received {}.".format(group))
        filt = group
        var_x_0 = Lambda(lambda var_x: var_x[..., :filt // 2])(var_x)
        var_x_1 = Lambda(lambda var_x: var_x[..., filt // 2:])(var_x)
        var_x_0 = Conv2D(filt // 2,
                         kernel_size=1,
                         kernel_regularizer=regularizers.l2(GAN22_REGULARIZER),
                         kernel_initializer=GAN22_CONV_INIT)(var_x_0)
        var_x_1 = InstanceNormalization()(var_x_1)
        var_x = concatenate([var_x_0, var_x_1], axis=-1)
    else:
        var_x = inp
    return var_x


def upscale_ps(inp, filters, initializer, use_norm=False, norm="none"):
    """ GAN Upscaler - Pixel Shuffler """
    var_x = Conv2D(filters * 4,
                   kernel_size=3,
                   kernel_regularizer=regularizers.l2(GAN22_REGULARIZER),
                   kernel_initializer=initializer,
                   padding="same")(inp)
    var_x = LeakyReLU(0.2)(var_x)
    var_x = normalization(var_x, norm, filters) if use_norm else var_x
    var_x = PixelShuffler()(var_x)
    return var_x


def upscale_nn(inp, filters, use_norm=False, norm="none"):
    """ GAN Neural Network """
    var_x = UpSampling2D()(inp)
    var_x = reflect_padding_2d(var_x, 1)
    var_x = Conv2D(filters,
                   kernel_size=3,
                   kernel_regularizer=regularizers.l2(GAN22_REGULARIZER),
                   kernel_initializer="he_normal")(var_x)
    var_x = normalization(var_x, norm, filters) if use_norm else var_x
    return var_x


def reflect_padding_2d(inp, pad=1):
    """ GAN Reflect Padding (2D) """
    var_x = Lambda(lambda var_x: tf.pad(var_x,
                                        [[0, 0], [pad, pad], [pad, pad], [0, 0]],
                                        mode="REFLECT"))(inp)
    return var_x


def conv_gan(inp, filters, use_norm=False, strides=2, norm='none'):
    """ GAN Conv Block """
    var_x = Conv2D(filters,
                   kernel_size=3,
                   strides=strides,
                   kernel_regularizer=regularizers.l2(GAN22_REGULARIZER),
                   kernel_initializer=GAN22_CONV_INIT,
                   use_bias=False,
                   padding="same")(inp)
    var_x = Activation("relu")(var_x)
    var_x = normalization(var_x, norm, filters) if use_norm else var_x
    return var_x


def conv_d_gan(inp, filters, use_norm=False, norm='none'):
    """ GAN Discriminator Conv Block """
    var_x = inp
    var_x = Conv2D(filters,
                   kernel_size=4,
                   strides=2,
                   kernel_regularizer=regularizers.l2(GAN22_REGULARIZER),
                   kernel_initializer=GAN22_CONV_INIT,
                   use_bias=False,
                   padding="same")(var_x)
    var_x = LeakyReLU(alpha=0.2)(var_x)
    var_x = normalization(var_x, norm, filters) if use_norm else var_x
    return var_x


def res_block_gan(inp, filters, use_norm=False, norm='none'):
    """ GAN Res Block """
    var_x = Conv2D(filters,
                   kernel_size=3,
                   kernel_regularizer=regularizers.l2(GAN22_REGULARIZER),
                   kernel_initializer=GAN22_CONV_INIT,
                   use_bias=False,
                   padding="same")(inp)
    var_x = LeakyReLU(alpha=0.2)(var_x)
    var_x = normalization(var_x, norm, filters) if use_norm else var_x
    var_x = Conv2D(filters,
                   kernel_size=3,
                   kernel_regularizer=regularizers.l2(GAN22_REGULARIZER),
                   kernel_initializer=GAN22_CONV_INIT,
                   use_bias=False,
                   padding="same")(var_x)
    var_x = add([var_x, inp])
    var_x = LeakyReLU(alpha=0.2)(var_x)
    var_x = normalization(var_x, norm, filters) if use_norm else var_x
    return var_x


def self_attn_block(inp, n_c, squeeze_factor=8):
    """ GAN Self Attention Block
    Code borrows from https://github.com/taki0112/Self-Attention-GAN-Tensorflow
    """
    msg = "Input channels must be >= {}, recieved nc={}".format(squeeze_factor, n_c)
    assert n_c // squeeze_factor > 0, msg
    var_x = inp
    shape_x = var_x.get_shape().as_list()

    var_f = Conv2D(n_c // squeeze_factor, 1,
                   kernel_regularizer=regularizers.l2(GAN22_REGULARIZER))(var_x)
    var_g = Conv2D(n_c // squeeze_factor, 1,
                   kernel_regularizer=regularizers.l2(GAN22_REGULARIZER))(var_x)
    var_h = Conv2D(n_c, 1, kernel_regularizer=regularizers.l2(GAN22_REGULARIZER))(var_x)

    shape_f = var_f.get_shape().as_list()
    shape_g = var_g.get_shape().as_list()
    shape_h = var_h.get_shape().as_list()
    flat_f = Reshape((-1, shape_f[-1]))(var_f)
    flat_g = Reshape((-1, shape_g[-1]))(var_g)
    flat_h = Reshape((-1, shape_h[-1]))(var_h)

    var_s = Lambda(lambda var_x: K.batch_dot(var_x[0],
                                             Permute((2, 1))(var_x[1])))([flat_g, flat_f])

    beta = Softmax(axis=-1)(var_s)
    var_o = Lambda(lambda var_x: K.batch_dot(var_x[0], var_x[1]))([beta, flat_h])
    var_o = Reshape(shape_x[1:])(var_o)
    var_o = Scale()(var_o)

    out = add([var_o, inp])
    return out
