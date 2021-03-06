import ast
import csv
import json
import os
import random
import nltk
import pandas
import untangle
import logging

from lstm.tokens import SENTENCE_END_TOKEN, UNKNOWN_TOKEN, MASK_TOKEN
from utils.commons import *
from utils.embed_utils import EmbeddingLoader


def get_loader(dataset):
    __LOADERS__ = {
        'opensub': (load_data_opensub, False),
        'shakespeare': (load_data_shakespeare, False),
        'yahoo': (load_data_yahoo, True),
        'southpark': (load_data_southpark, True),
        'cornell': (load_data_cornell, True),
        'songs': (load_data_lyrics, True),
        'vnnews': (load_data_vnnews, True)
    }

    try:
        return __LOADERS__[dataset]
    except KeyError:
        raise ValueError("Invalid dataset %s" % dataset)


def load_embedding(vocabulary_size, embed_type='glove', embed_path='data/glove.6B.100d.txt'):
    logging.info("Loading word embedding from %s ..." % embed_path)
    logging.info('Using vocabulary size %d' % vocabulary_size)

    __EMBED_LOADERS__ = {
        'glove': EmbeddingLoader.load_stanford_glove,
        'fasttext': EmbeddingLoader.load_fb_fasttext,
    }

    embed = __EMBED_LOADERS__[embed_type](embed_path)
    embed_layer = np.asarray(embed.word_vectors[:vocabulary_size - 3, :], dtype=np.float32)
    index_to_word = list(embed.inverse_dictionary.values())
    index_to_word = index_to_word[:vocabulary_size - 3]
    index_to_word.insert(0, MASK_TOKEN)
    index_to_word.append(SENTENCE_END_TOKEN)
    index_to_word.append(UNKNOWN_TOKEN)
    word_to_index = dict([(w, i) for i, w in enumerate(index_to_word)])

    word_dim = np.size(embed_layer, 1)
    # Vector for the MASK token
    embed_layer = np.vstack((np.zeros((1, word_dim), dtype=np.float32), embed_layer))
    # TODO Embed meaning for SENTENCE_END_TOKEN
    embed_layer = np.vstack((embed_layer, np.asarray(np.random.uniform(15.0, 30.0, (1, word_dim)), dtype=np.float32)))
    # Random vector for UNKNOWN_TOKEN, placed intentionally far away from vocabulary words
    embed_layer = np.vstack((embed_layer, np.asarray(np.random.uniform(50.0, 80.0, (1, word_dim)), dtype=np.float32)))

    logging.info('Done.')
    return embed_layer, word_to_index, index_to_word


def replace_unknown(raw_x, raw_y, word_to_index):
    # Replace all words not in our vocabulary with the unknown token
    # Keep track of the unknown token ratio
    unk_count = 0.0
    total = 0.0
    for i, sent in enumerate(raw_x):
        idx = 0
        for w in sent:
            if w in word_to_index:
                nw = w
            else:
                nw = UNKNOWN_TOKEN
                unk_count += 1.0
            total += 1.0
            raw_x[i][idx] = nw
            idx += 1
    for i, sent in enumerate(raw_y):
        idx = 0
        for w in sent:
            if w in word_to_index:
                nw = w
            else:
                nw = UNKNOWN_TOKEN
                unk_count += 1.0
            total += 1.0
            raw_y[i][idx] = nw
            idx += 1
    logging.info("Parsed %s exchanges." % (len(raw_x)))
    logging.info("%s unknown tokens / %s tokens " % (int(unk_count), int(total)))
    logging.info("Unknown token ratio: %s %%" % (unk_count * 100 / total))

    return raw_x, raw_y


def generate_data(raw_x, raw_y, sequence_len, embed_layer, word_to_index, vec_labels):
    logging.info('Generating data...')
    X_train = np.zeros((len(raw_x), sequence_len), dtype=np.int32)
    for i in range(len(raw_x)):
        for j in range(len(raw_x[i])):
            X_train[i][j] = word_to_index[raw_x[i][j]]

    output_mask = np.ones((len(raw_y), sequence_len), dtype=np.float32)
    if vec_labels:
        y_train = np.zeros((len(raw_y), sequence_len, np.size(embed_layer, 1)), dtype=np.float32)
        for i in range(len(raw_y)):
            for j in range(len(raw_y[i])):
                y_train[i][j] = embed_layer[word_to_index[raw_y[i][j]]]
    else:
        y_train = np.zeros((len(raw_y), sequence_len), dtype=np.float32)
        for i in range(len(raw_y)):
            for j in range(len(raw_y[i])):
                p = word_to_index[raw_y[i][j]]
                y_train[i][j] = p
                if raw_y[i][j] == SENTENCE_END_TOKEN:
                    for k in range(j + 1, sequence_len):
                        output_mask[i][k] = 0

    return X_train, y_train, output_mask


def generate_lm_labels(x, word_to_index):
    ends = np.zeros((np.size(x, 0), 1))
    y = np.hstack((x[:, 1:], ends))

    for i in range(np.size(y, 0)):
        for j in range(1, np.size(y, 1)):
            if x[i][j] == word_to_index[MASK_TOKEN]:
                y[i][j - 1] = word_to_index[SENTENCE_END_TOKEN]
                break
            if j == np.size(y, 1) - 1:
                y[i][j] = word_to_index[SENTENCE_END_TOKEN]

    msk_func = np.vectorize(lambda a: 0 if a in (word_to_index[MASK_TOKEN], word_to_index[UNKNOWN_TOKEN]) else 1)
    output_mask = msk_func(y)
    return y, output_mask


def load_data_yahoo(embed_layer, word_to_index, index_to_word,
                    filename="data/yahoo/nfL6.json", sample_size=None,
                    sequence_len=2000, vec_labels=True, **kwargs):
    logging.info("Reading JSON file (%s) ..." % filename)
    questions = []
    answers = []
    with open(filename, 'r') as f:
        data = json.load(f)
        if sample_size is not None:
            data = random.sample(data, sample_size)
        for qa in data:
            questions.append("%s" % qa['question'].lower())
            answers.append("%s %s" % (qa['answer'].lower(), SENTENCE_END_TOKEN))

    logging.info("Tokenizing...")
    tokenized_questions = [nltk.word_tokenize(sent) for sent in questions]
    tokenized_answers = [nltk.word_tokenize(sent) for sent in answers]

    tokenized_questions, tokenized_answers = replace_unknown(tokenized_answers, tokenized_questions, word_to_index)

    # Create the training data
    logging.info('Generating data...')
    X_train, y_train, output_mask = generate_data(tokenized_questions, tokenized_answers, sequence_len,
                                                  embed_layer, word_to_index, vec_labels)

    return X_train, y_train, [], output_mask


def load_data_opensub(embed_layer, word_to_index, index_to_word,
                      path='./data/opensub', sample_size=None,
                      sequence_len=50, vec_labels=True, **kwargs):
    raw_x, raw_y = [], []
    fl = os.listdir(path)
    if sample_size is not None:
        np.random.shuffle(fl)
        fl = fl[:sample_size]

    samples = []
    logging.info('Tokenizing...')
    for fn in fl:
        logging.info('Reading %s...' % fn)
        f = open(path + '/' + fn, 'rt')
        lines = f.readlines()
        samples.append(lines[random.randint(0, len(lines) - 1)].rstrip())
        for i, l in enumerate(lines[:-1]):
            l1 = nltk.word_tokenize(l.rstrip().lower())[:sequence_len]
            l2 = nltk.word_tokenize(lines[i + 1].rstrip().lower())[:sequence_len - 1]
            l2.append(SENTENCE_END_TOKEN)
            raw_x.append(l1)
            raw_y.append(l2)

    raw_x, raw_y = replace_unknown(raw_x, raw_y, word_to_index)

    X_train, y_train, output_mask = generate_data(raw_x, raw_y, sequence_len, embed_layer,
                                                  word_to_index, vec_labels)

    return X_train, y_train, samples, output_mask


def load_data_lyrics(embed_layer, word_to_index, index_to_word,
                     path='./data/songdata.csv', sample_size=None,
                     sequence_len=50, vec_labels=True, **kwargs):
    logging.info('Reading CSV file %s...' % path)
    frames = pandas.read_csv(path, header=0, names=['song', 'text'])
    frames = frames.apply(lambda x: x.replace('\n', '. '), axis=1)
    samples = frames.sample(100).values
    if sample_size is not None:
        frames = frames.sample(n=sample_size)

    raw_x = frames['song'].values
    raw_y = frames['text'].values

    raw_x, raw_y = replace_unknown(raw_x, raw_y, word_to_index)
    X_train, y_train, output_mask = generate_data(raw_x, raw_y, sequence_len, embed_layer,
                                                  word_to_index, vec_labels)
    return X_train, y_train, samples, output_mask


def load_data_shakespeare(embed_layer, word_to_index, index_to_word,
                          path='./data/shakespeare', sample_size=None,
                          sequence_len=2000, vec_labels=True, **kwargs):
    def load_play(file_path):
        play = untangle.parse(file_path)
        acts = play.PLAY.ACT
        q, a = [], []

        for act in acts:
            scenes = act.SCENE
            for scene in scenes:
                s_q, s_a = [], []
                speeches = scene.SPEECH
                for speech in speeches:
                    lines = speech.LINE
                    line_str = []
                    for line in lines:
                        line_st = line.cdata
                        if len(line_st) == 0:
                            continue
                        if line_st[-1].isalpha():
                            line_st += '.'
                        speech_tokens = nltk.word_tokenize(line_st.lower())
                        s_q.append(speech_tokens)
                        if len(s_q) > 1:
                            s_a.append(speech_tokens + [SENTENCE_END_TOKEN])
                            # line_str.append(line_st)
                            # speech_str = ' '.join(line_str)
                            # speech_tokens = nltk.word_tokenize(speech_str.lower())
                            # s_q.append(speech_tokens)
                            # if len(s_q) > 1:
                            #     s_a.append(speech_tokens)
                s_q = s_q[:-1]
                q.extend(s_q)
                a.extend(s_a)
        assert len(q) == len(a)
        return q, a

    raw_x, raw_y = [], []
    fl = os.listdir(path)

    if sample_size is not None:
        np.random.shuffle(fl)
        fl = fl[:sample_size]

    logging.info('Tokenizing...')
    for fn in fl:
        if not fn.endswith('.xml'):
            continue
        logging.info('Reading %s...' % fn)
        rx, ry = load_play(path + '/' + fn)
        raw_x.extend(rx)
        raw_y.extend(ry)

    samples = []

    raw_x, raw_y = replace_unknown(raw_x, raw_y, word_to_index)

    X_train, y_train, output_mask = generate_data(raw_x, raw_y, sequence_len, embed_layer,
                                                  word_to_index, vec_labels)

    return X_train, y_train, samples, output_mask


def load_data_southpark(embed_layer, word_to_index, index_to_word,
                        path='./data/southpark/southpark.csv', sample_size=None,
                        sequence_len=2000, vec_labels=True, **kwargs):
    logging.info("Reading CSV file (%s) ..." % path)
    f = open(path, mode='rt', newline='')
    reader = csv.reader(f, delimiter=',', quotechar='"')
    rows = []
    for row in reader:
        rows.append(row)
    f.close()

    samples = []
    character = kwargs.get('character', None)

    logging.info('Tokenizing...')
    season, ep = rows[0][0], rows[0][1]
    prev_line = rows[0][3]
    raw_x, raw_y = [], []
    for r in rows[1:]:
        ss, e, ch, line = r[0], r[1], r[2], r[3]
        if character is not None and ch != character:
            prev_line = line
            continue
        if season != ss or ep != e:
            logging.info('Season %s ep %s' % (season, ep))
            samples.append(line)
            season = ss
            ep = e
            continue

        l1 = nltk.word_tokenize(prev_line.lower().strip())[:sequence_len]
        l2 = nltk.word_tokenize(line.lower().strip())[:sequence_len - 1]
        l2.append(SENTENCE_END_TOKEN)
        raw_x.append(l1)
        raw_y.append(l2)
        if sample_size is not None and len(raw_x) >= sample_size:
            break
        prev_line = line

    raw_x, raw_y = replace_unknown(raw_x, raw_y, word_to_index)

    X_train, y_train, output_mask = generate_data(raw_x, raw_y, sequence_len, embed_layer,
                                                  word_to_index, vec_labels)

    return X_train, y_train, samples, output_mask


def load_data_cornell(embed_layer, word_to_index, index_to_word,
                      path='./data/cornell_movies/cornell_movie-dialogs_corpus', sample_size=None,
                      sequence_len=2000, vec_labels=True, **kwargs):
    logging.info('Reading TXT file (%s)' % path)
    f1 = open(path + '/movie_lines.txt', mode='rt', encoding='cp437')
    f2 = open(path + '/movie_conversations.txt', mode='rt')
    lines = f1.readlines()
    convs = f2.readlines()
    f1.close(), f2.close()

    samples = []
    raw_x, raw_y = [], []
    id_to_lines = {}
    for line in lines:
        fields = line[:-1].split(' +++$+++ ')
        id_to_lines[fields[0]] = fields[-1]

    logging.info('Tokenizing...')
    for conv in convs:
        expr = conv[:-1].split(' +++$+++ ')[-1]
        lns = ast.literal_eval(expr)
        tlns = [nltk.word_tokenize(id_to_lines[l].lower().strip()) for l in lns]
        for i in range(len(tlns) - 1):
            x = tlns[i][:sequence_len]
            y = tlns[i + 1][:sequence_len - 1]
            y.append(SENTENCE_END_TOKEN)
            raw_x.append(x)
            raw_y.append(y)

        if sample_size is not None and len(raw_x) >= sample_size:
            break

    raw_x, raw_y = replace_unknown(raw_x, raw_y, word_to_index)
    X_train, y_train, output_mask = generate_data(raw_x, raw_y, sequence_len, embed_layer,
                                                  word_to_index, vec_labels)

    return X_train, y_train, samples, output_mask


def load_data_vnnews(embed_layer, word_to_index, index_to_word,
                     path='./data/vnnews/vnnews_train.txt', sample_size=None,
                     sequence_len=2000, vec_labels=True, **kwargs):
    logging.info('Reading TXT file (%s)' % path)
    f = open(path, 'rt')
    lines = [l[:-1] for l in f.readlines()]
    samples = []

    if sample_size is not None:
        samples = lines[:sample_size]
        lines = lines[sample_size:]

    raw_x = []
    logging.info('Tokenizing')
    for line in lines:
        raw_x.append(nltk.word_tokenize(line.lower().strip())[:sequence_len])

    raw_x, raw_y = replace_unknown(raw_x, raw_x, word_to_index)
    X_train, y_train, output_mask = generate_data(raw_x, raw_y, sequence_len, embed_layer,
                                                  word_to_index, vec_labels)

    return X_train, y_train, samples, output_mask