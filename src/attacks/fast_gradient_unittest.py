from __future__ import absolute_import, division, print_function, unicode_literals

import unittest

import keras
import keras.backend as k
from keras.models import Sequential
from keras.layers import Dense, Activation, Flatten, Conv2D, MaxPooling2D, Dropout
import numpy as np
import tensorflow as tf

from src.attacks.fast_gradient import FastGradientMethod
from src.classifiers.keras import KerasClassifier
from src.classifiers.tensorflow import TFClassifier
from src.utils import load_mnist, get_labels_np_array

BATCH_SIZE = 10
NB_TRAIN = 100
NB_TEST = 11


class TestFastGradientMethod(unittest.TestCase):

    def setUp(self):
        k.set_learning_phase(1)

        # Get MNIST
        (x_train, y_train), (x_test, y_test), _, _ = load_mnist()
        x_train, y_train, x_test, y_test = x_train[:NB_TRAIN], y_train[:NB_TRAIN], x_test[:NB_TEST], y_test[:NB_TEST]
        self.mnist = ((x_train, y_train), (x_test, y_test))
        im_shape = x_train[0].shape

        # Create basic CNN on MNIST using Keras
        model = Sequential()
        model.add(Conv2D(32, kernel_size=(3, 3), activation='relu', input_shape=im_shape))
        model.add(Conv2D(64, (3, 3), activation='relu'))
        model.add(MaxPooling2D(pool_size=(2, 2)))
        model.add(Dropout(0.25))
        model.add(Flatten())
        model.add(Dense(128, activation='relu'))
        model.add(Dropout(0.5))
        model.add(Dense(10, activation='softmax'))

        model.compile(loss=keras.losses.categorical_crossentropy, optimizer=keras.optimizers.Adadelta(),
                      metrics=['accuracy'])

        model.fit(x_train, y_train, batch_size=BATCH_SIZE, epochs=1)
        self.classifier_k = KerasClassifier((0, 1), model, use_logits=False)

        scores = self.classifier_k._model.evaluate(x_train, y_train)
        print("\n[Keras, MNIST] Accuracy on training set: %.2f%%" % (scores[1] * 100))
        scores = self.classifier_k._model.evaluate(x_test, y_test)
        print("\n[Keras, MNIST] Accuracy on test set: %.2f%%" % (scores[1] * 100))

        # Create basic CNN on MNIST using TensorFlow
        labels_tf = tf.placeholder(tf.float32, [None, 10])
        inputs_tf = tf.placeholder(tf.float32, [None] + list(x_train.shape[1:]))
        logits_tf, loss_tf = self._cnn_mnist_tf(inputs_tf, labels_tf, tf.estimator.ModeKeys.TRAIN)

        sess = tf.Session()
        sess.run(tf.global_variables_initializer())
        optimizer_tf = tf.train.GradientDescentOptimizer(.5)
        train_tf = optimizer_tf.minimize(loss_tf)

        self.classifier_tf = TFClassifier((0, 1), inputs_tf, logits_tf, use_logits=False, loss=loss_tf,
                                          train=train_tf, output_ph=labels_tf, sess=sess)
        self.classifier_tf.fit(x_train, y_train, nb_epochs=1, batch_size=BATCH_SIZE)

        scores = get_labels_np_array(self.classifier_tf.predict(x_train))
        acc = np.sum(np.argmax(scores, axis=1) == np.argmax(y_train, axis=1)) / y_train.shape[0]
        print('\n[TF, MNIST] Accuracy on training set: %.2f%%' % (acc * 100))

        scores = get_labels_np_array(self.classifier_tf.predict(x_test))
        acc = np.sum(np.argmax(scores, axis=1) == np.argmax(y_test, axis=1)) / y_test.shape[0]
        print('\n[TF, MNIST] Accuracy on test set: %.2f%%' % (acc * 100))

    def test_mnist(self):
        # Define all backends to test
        backends = {'keras': self.classifier_k,
                    'tf': self.classifier_tf}

        for _, classifier in backends.items():
            self._test_backend_mnist(classifier)

    def _test_backend_mnist(self, classifier):
        # Get MNIST
        (x_train, y_train), (x_test, y_test), _, _ = load_mnist()
        x_train, y_train = x_train[:NB_TRAIN], y_train[:NB_TRAIN]
        x_test, y_test = x_test[:NB_TEST], y_test[:NB_TEST]

        # Test FGSM with np.inf norm
        attack = FastGradientMethod(classifier, eps=1)
        x_test_adv = attack.generate(x_test)
        x_train_adv = attack.generate(x_train)

        self.assertFalse((x_train == x_train_adv).all())
        self.assertFalse((x_test == x_test_adv).all())

        train_y_pred = get_labels_np_array(classifier.predict(x_train_adv))
        test_y_pred = get_labels_np_array(classifier.predict(x_test_adv))

        self.assertFalse((y_train == train_y_pred).all())
        self.assertFalse((y_test == test_y_pred).all())

        acc = np.sum(np.argmax(train_y_pred, axis=1) == np.argmax(y_train, axis=1)) / y_train.shape[0]
        print('\nAccuracy on adversarial train examples: %.2f%%' % (acc * 100))

        acc = np.sum(np.argmax(test_y_pred, axis=1) == np.argmax(y_test, axis=1)) / y_test.shape[0]
        print('\nAccuracy on adversarial test examples: %.2f%%' % (acc * 100))

        # Test minimal perturbations
        attack_params = {"minimal": True,
                         "eps_step": .1,
                         "eps_max": 1.}

        x_train_adv_min = attack.generate(x_train, **attack_params)
        x_test_adv_min = attack.generate(x_test, **attack_params)

        self.assertFalse((x_train_adv_min == x_train_adv).all())
        self.assertFalse((x_test_adv_min == x_test_adv).all())

        self.assertFalse((x_train == x_train_adv_min).all())
        self.assertFalse((x_test == x_test_adv_min).all())

        train_y_pred = get_labels_np_array(classifier.predict(x_train_adv_min))
        test_y_pred = get_labels_np_array(classifier.predict(x_test_adv_min))

        self.assertFalse((y_train == train_y_pred).all())
        self.assertFalse((y_test == test_y_pred).all())

        acc = np.sum(np.argmax(train_y_pred, axis=1) == np.argmax(y_train, axis=1)) / y_train.shape[0]
        print('\nAccuracy on adversarial train examples with minimal perturbation: %.2f%%' % (acc * 100))

        acc = np.sum(np.argmax(test_y_pred, axis=1) == np.argmax(y_test, axis=1)) / y_test.shape[0]
        print('\nAccuracy on adversarial test examples with minimal perturbation: %.2f%%' % (acc * 100))

        # L_1 norm
        attack = FastGradientMethod(classifier, eps=1, norm=1)
        x_test_adv = attack.generate(x_test)
        self.assertFalse((x_test == x_test_adv).all())

        test_y_pred = get_labels_np_array(classifier.predict(x_test_adv))
        self.assertFalse((y_test == test_y_pred).all())
        acc = np.sum(np.argmax(test_y_pred, axis=1) == np.argmax(y_test, axis=1)) / y_test.shape[0]
        print('\nAccuracy on adversarial test examples with L1 norm: %.2f%%' % (acc * 100))

        # L_2 norm
        attack = FastGradientMethod(classifier, eps=1, norm=2)
        x_test_adv = attack.generate(x_test)
        self.assertFalse((x_test == x_test_adv).all())

        test_y_pred = get_labels_np_array(classifier.predict(x_test_adv))
        self.assertFalse((y_test == test_y_pred).all())
        acc = np.sum(np.argmax(test_y_pred, axis=1) == np.argmax(y_test, axis=1)) / y_test.shape[0]
        print('\nAccuracy on adversarial test examples with L2 norm: %.2f%%' % (acc * 100))

    # def test_with_preprocessing(self):
    #
    #     session = tf.Session()
    #     k.set_session(session)
    #
    #     comp_params = {"loss": 'categorical_crossentropy',
    #                    "optimizer": 'adam',
    #                    "metrics": ['accuracy']}
    #
    #     # get MNIST
    #     batch_size, nb_train, nb_test = 100, 1000, 100
    #     (X_train, Y_train), (X_test, Y_test), _, _ = load_mnist()
    #     X_train, Y_train = X_train[:nb_train], Y_train[:nb_train]
    #     X_test, Y_test = X_test[:nb_test], Y_test[:nb_test]
    #     im_shape = X_train[0].shape
    #
    #     # get classifier
    #     classifier = CNN(im_shape, act="relu", defences=["featsqueeze1"])
    #     classifier.compile(comp_params)
    #     classifier.fit(X_train, Y_train, epochs=1, batch_size=batch_size)
    #     scores = classifier.evaluate(X_train, Y_train)
    #     print("\naccuracy on training set: %.2f%%" % (scores[1] * 100))
    #     scores = classifier.evaluate(X_test, Y_test)
    #     print("\naccuracy on test set: %.2f%%" % (scores[1] * 100))
    #
    #     attack = FastGradientMethod(classifier, eps=1)
    #     X_train_adv = attack.generate(X_train)
    #     X_test_adv = attack.generate(X_test)
    #
    #     self.assertFalse((X_train == X_train_adv).all())
    #     self.assertFalse((X_test == X_test_adv).all())
    #
    #     train_y_pred = get_labels_np_array(classifier.predict(X_train_adv))
    #     test_y_pred = get_labels_np_array(classifier.predict(X_test_adv))
    #
    #     self.assertFalse((Y_train == train_y_pred).all())
    #     self.assertFalse((Y_test == test_y_pred).all())
    #
    #     scores = classifier.evaluate(X_train_adv, Y_train)
    #     print('\naccuracy on adversarial train examples: %.2f%%' % (scores[1] * 100))
    #
    #     scores = classifier.evaluate(X_test_adv, Y_test)
    #     print('\naccuracy on adversarial test examples: %.2f%%' % (scores[1] * 100))

    @staticmethod
    def _cnn_mnist_tf(inputs, labels, mode):
        """ Implement a CNN for MNIST in TensorFlow."""
        # Input Layer
        input_layer = tf.reshape(inputs, [-1, 28, 28, 1])

        conv1 = tf.layers.conv2d(inputs=input_layer, filters=32, kernel_size=[5, 5], padding="same",
                                 activation=tf.nn.relu)
        pool1 = tf.layers.max_pooling2d(inputs=conv1, pool_size=[2, 2], strides=2)
        conv2 = tf.layers.conv2d(inputs=pool1, filters=64, kernel_size=[5, 5], padding="same", activation=tf.nn.relu)
        pool2 = tf.layers.max_pooling2d(inputs=conv2, pool_size=[2, 2], strides=2)
        pool2_flat = tf.reshape(pool2, [-1, 7 * 7 * 64])
        dense = tf.layers.dense(inputs=pool2_flat, units=1024, activation=tf.nn.relu)
        dropout = tf.layers.dropout(inputs=dense, rate=0.4, training=mode == tf.estimator.ModeKeys.TRAIN)
        logits = tf.layers.dense(inputs=dropout, units=10)

        loss = tf.losses.softmax_cross_entropy(onehot_labels=labels, logits=logits)
        return logits, loss


if __name__ == '__main__':
    unittest.main()
