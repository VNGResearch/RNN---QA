LEARNING_RATE = 0.001
VOCABULARY_SIZE = 30000
N_EPOCH = 5
QUERY_FILE = './queries.txt'
SEQUENCE_LENGTH = 50
ENCODER_OUTPUTS = (1500,)
DECODER_OUTPUTS = (1500,)
DATA_SIZE = 1000  # Number of conversations to extract from yahoo, cornell or southpark dataset
DOC_COUNT = 1  # Number of documents to extract from opensub or shakespeare dataset
VAL_SPLIt = 50  # Number of validation samples to be taken from training set
BATCH_SIZE = 20
DATASET = 'cornell'

# Structural settings
OUTPUT_TYPE = 1
DECODER_TYPE = 2
