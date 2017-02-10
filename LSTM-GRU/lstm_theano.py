import numpy as np
import theano as theano
import theano.tensor as T


class LSTMTheano:

    def __init__(self, word_dim=400003, hidden_dim=50, bptt_truncate=-1, embedder=None):
        # Assign instance variables
        self.hidden_dim = hidden_dim
        self.bptt_truncate = bptt_truncate
        self.word_dim = word_dim
        # Initialize the network parameters
        if embedder is None:
            E = np.random.uniform(-np.sqrt(1. / word_dim), np.sqrt(1. / word_dim), (hidden_dim, word_dim))
            self.embedded = False
        else:
            E = np.transpose(embedder)
            self.embedded = True

        U = np.random.uniform(-np.sqrt(1. / hidden_dim), np.sqrt(1. / hidden_dim), (8, hidden_dim, hidden_dim))
        W = np.random.uniform(-np.sqrt(1. / hidden_dim), np.sqrt(1. / hidden_dim), (8, hidden_dim, hidden_dim))
        V = np.random.uniform(-np.sqrt(1. / hidden_dim), np.sqrt(1. / hidden_dim), (word_dim, hidden_dim))
        b = np.zeros((8, hidden_dim))
        c = np.zeros(word_dim)
        # Theano: Created shared variables
        self.E = theano.shared(name='E', value=E.astype(theano.config.floatX))
        self.U = theano.shared(name='U', value=U.astype(theano.config.floatX))
        self.W = theano.shared(name='W', value=W.astype(theano.config.floatX))
        self.V = theano.shared(name='V', value=V.astype(theano.config.floatX))
        self.b = theano.shared(name='b', value=b.astype(theano.config.floatX))
        self.c = theano.shared(name='c', value=c.astype(theano.config.floatX))
        # SGD / rmsprop: Initialize parameters
        self.mE = theano.shared(name='mE', value=np.zeros(E.shape).astype(theano.config.floatX))
        self.mU = theano.shared(name='mU', value=np.zeros(U.shape).astype(theano.config.floatX))
        self.mV = theano.shared(name='mV', value=np.zeros(V.shape).astype(theano.config.floatX))
        self.mW = theano.shared(name='mW', value=np.zeros(W.shape).astype(theano.config.floatX))
        self.mb = theano.shared(name='mb', value=np.zeros(b.shape).astype(theano.config.floatX))
        self.mc = theano.shared(name='mc', value=np.zeros(c.shape).astype(theano.config.floatX))
        # We store the Theano graph here
        self.theano = {}
        print('Building theano graph...')
        self.__theano_build__()

    def __theano_build__(self):
        E, V, U, W, b, c, embedded = self.E, self.V, self.U, self.W, self.b, self.c, self.embedded

        x = T.ivector('x')
        y = T.ivector('y')

        def forward_prop_step(x_t, s_t1_prev, c_t1_prev, s_t2_prev, c_t2_prev):
            # This is how we calculated the hidden state in a simple RNN. No longer!
            # s_t = T.tanh(U[:,x_t] + W.dot(s_t1_prev))

            # Word embedding layer
            x_e = E[:, x_t]

            # LSTM Layer
            i_t1 = T.nnet.hard_sigmoid(U[0].dot(x_e) + W[0].dot(s_t1_prev) + b[0])
            f_t1 = T.nnet.hard_sigmoid(U[1].dot(x_e) + W[1].dot(s_t1_prev) + b[1])
            o_t1 = T.nnet.hard_sigmoid(U[2].dot(x_e) + W[2].dot(s_t1_prev) + b[2])
            g_t1 = T.tanh(U[3].dot(x_e) + W[3].dot(s_t1_prev) + b[3])
            c_t1 = c_t1_prev * f_t1 + g_t1 * i_t1
            s_t1 = T.tanh(c_t1) * o_t1

            i_t2 = T.nnet.hard_sigmoid(U[4].dot(s_t1) + W[4].dot(s_t2_prev) + b[4])
            f_t2 = T.nnet.hard_sigmoid(U[5].dot(s_t1) + W[5].dot(s_t2_prev) + b[5])
            o_t2 = T.nnet.hard_sigmoid(U[6].dot(s_t1) + W[6].dot(s_t2_prev) + b[6])
            g_t2 = T.tanh(U[7].dot(s_t1) + W[7].dot(s_t2_prev) + b[7])
            c_t2 = c_t2_prev * f_t2 + g_t2 * i_t2
            s_t2 = T.tanh(c_t2) * o_t2

            # Final output calculation
            # Theano's softmax returns a matrix with one row, we only need the row
            o_t = T.nnet.softmax(V.dot(s_t2) + c)[0]

            return [o_t, s_t1, c_t1, s_t2, c_t2]

        [o, s1, cm1, s2, cm2], updates = theano.scan(
            forward_prop_step,
            sequences=x,
            truncate_gradient=self.bptt_truncate,
            outputs_info=[None,
                          dict(initial=T.zeros(self.hidden_dim)),
                          dict(initial=T.zeros(self.hidden_dim)),
                          dict(initial=T.zeros(self.hidden_dim)),
                          dict(initial=T.zeros(self.hidden_dim)), ])

        prediction = T.argmax(o, axis=1)
        o_error = T.sum(T.nnet.categorical_crossentropy(o, y))

        # Total cost (could add regularization here)
        cost = o_error

        # Gradients
        dE = T.grad(cost, E)
        dU = T.grad(cost, U)
        dW = T.grad(cost, W)
        db = T.grad(cost, b)
        dV = T.grad(cost, V)
        dc = T.grad(cost, c)

        # Assign functions
        self.predict = theano.function([x], o)
        self.predict_class = theano.function([x], prediction)
        self.ce_error = theano.function([x, y], cost)
        if not embedded:
            self.bptt = theano.function([x, y], [dE, dU, dW, db, dV, dc])
        else:
            self.bptt = theano.function([x, y], [dU, dW, db, dV, dc])

        # SGD parameters
        learning_rate = T.scalar('learning_rate')
        decay = T.scalar('decay')

        # rmsprop cache updates
        mE = decay * self.mE + (1 - decay) * dE ** 2
        mU = decay * self.mU + (1 - decay) * dU ** 2
        mW = decay * self.mW + (1 - decay) * dW ** 2
        mV = decay * self.mV + (1 - decay) * dV ** 2
        mb = decay * self.mb + (1 - decay) * db ** 2
        mc = decay * self.mc + (1 - decay) * dc ** 2

        if not embedded:
            self.sgd_step = theano.function(
                [x, y, learning_rate, theano.In(decay, value=0.9)],
                [],
                updates=[(E, E - learning_rate * dE / T.sqrt(mE + 1e-6)),
                         (U, U - learning_rate * dU / T.sqrt(mU + 1e-6)),
                         (W, W - learning_rate * dW / T.sqrt(mW + 1e-6)),
                         (V, V - learning_rate * dV / T.sqrt(mV + 1e-6)),
                         (b, b - learning_rate * db / T.sqrt(mb + 1e-6)),
                         (c, c - learning_rate * dc / T.sqrt(mc + 1e-6)),
                         (self.mE, mE),
                         (self.mU, mU),
                         (self.mW, mW),
                         (self.mV, mV),
                         (self.mb, mb),
                         (self.mc, mc)
                         ])
        else:
            self.sgd_step = theano.function(
                [x, y, learning_rate, theano.In(decay, value=0.9)],
                [],
                updates=[(U, U - learning_rate * dU / T.sqrt(mU + 1e-6)),
                         (W, W - learning_rate * dW / T.sqrt(mW + 1e-6)),
                         (V, V - learning_rate * dV / T.sqrt(mV + 1e-6)),
                         (b, b - learning_rate * db / T.sqrt(mb + 1e-6)),
                         (c, c - learning_rate * dc / T.sqrt(mc + 1e-6)),
                         (self.mU, mU),
                         (self.mW, mW),
                         (self.mV, mV),
                         (self.mb, mb),
                         (self.mc, mc)
                         ])

    def calculate_total_loss(self, X, Y):
        return np.sum([self.ce_error(x, y) for x, y in zip(X, Y)])

    def calculate_loss(self, X, Y):
        # Divide calculate_loss by the number of words
        num_words = np.sum([len(y) for y in Y])
        return self.calculate_total_loss(X, Y) / float(num_words)
