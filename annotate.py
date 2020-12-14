from argparse import ArgumentParser
from bisect import insort
from heapq import heapify, heappop
from itertools import product
from lxml import etree
import logging
import math
import numpy as np
from scrape import tokenize_title

def is_subsequence(pattern, entry):
    # If the pattern is empty then it's trivially a subsequence of any entry.
    if not pattern:
        return True

    # If the entry is empty then no pattern can be a subsequence of it.
    if not entry:
        return False

    # If the last items of the entry and the pattern match, discard these items
    # and keep checking for subsequence.
    if pattern[-1] == entry[-1]:
        return is_subsequence(pattern[:-1], entry[:-1])

    # Else, discard the last item from the entry and keep checking for
    # subsequence.
    return is_subsequence(pattern, entry[:-1])

def get_title_match(query):
    def serialize(parent):
        title_node = etree.SubElement(parent, 'title')
        title_node.text = query

    pattern = query.split()
    return {
        'pattern' : pattern,
        'transactions' : set(),
        'serialize' : serialize,

        # Check for subsequence match in case of sequential patterns.
        'test' : lambda node: is_subsequence(
            pattern, node.find('label').text.split()
        ),
    }

def get_author_match(query):
    pattern = set(query.split(sep=' ; '))

    def serialize(parent):
        for author in pattern:
            author_node = etree.SubElement(parent, 'author')
            author_node.text = author

    return {
        'pattern' : pattern,
        'transactions' : set(),
        'serialize' : serialize,

        # Check for subset match in case of itemset patterns.
        'test' : lambda node: pattern.issubset(
            map(
                lambda author_node: author_node.text,
                node.findall('author')
            )
        ),
    }

def add_matches(has_query_type, pattern_file, match_fn, matches, query_match):
    for pattern in pattern_file:
        match = match_fn(pattern.rstrip('\n'))

        pattern = match['pattern']
        query_pattern = query_match['pattern']

        # Don't add a pattern to the list of matches if it's the same as the
        # query.
        if has_query_type and pattern == query_pattern:
            query_match = match
        else:
            matches.append(match)

    return query_match

def cosine_sim(a, b):
    a_norm = np.linalg.norm(a)
    b_norm = np.linalg.norm(b)

    if a_norm == 0 or b_norm == 0:
        if a_norm == b_norm:
            return 0
        else:
            return 1

    # sim(a,b) = (a • b) / (|a| * |b|)
    sim = np.dot(a, b) / (a_norm * b_norm)

    logging.debug('sim={}'.format(sim))

    return sim

def mutual_info(matchA, matchB, total):
    def single_probability(a):
        return [
            # P(X=0) = (|D| - |Da|) / |D|
            (total - len(a) + 0.5) / (total + 1),

            # P(X=1) = |Da| / |D|
            (len(a) + 0.5) / (total + 1),
        ]

    a = matchA['transactions']
    b = matchB['transactions']

    p_a = single_probability(a)
    p_b = single_probability(b)

    logging.debug('P({})={}'.format(matchA['pattern'], p_a))
    logging.debug('P({})={}'.format(matchB['pattern'], p_b))

    p_ab = [
        [
            # P(X=0,Y=0) = (|D| - |Da v Db|) / |D|
            (total - len(a.union(b)) + 0.25) / (total + 1),

            # P(X=0,Y=1) = (|Db| - |Da ^ Db|) / |D|
            (len(b) - len(a.intersection(b)) + 0.25) / (total + 1),
        ],
        [
            # P(X=1,Y=0) = (|Da| - |Da ^ Db|) / |D|
            (len(a) - len(a.intersection(b)) + 0.25) / (total + 1),

            # P(X=1,Y=1) = |Da ^ Db| / |D|
            (len(a.intersection(b)) + 0.25) / (total + 1),
        ],
    ]

    logging.debug('P(A,B)={}'.format(p_ab))

    mi = sum([
        p_ab[x][y] * math.log2(p_ab[x][y] / (p_a[x] * p_b[y]))
        for x, y in product([0, 1], [0, 1])
    ])

    logging.debug('MI={}'.format(mi))

    return mi

def pick_largest_k(itemList, fn, k):
    scored_items = [
        (-fn(item), ix, item)
        for ix, item in enumerate(itemList)
    ]

    heapify(scored_items)

    return list(
        map(
            lambda item: (-item[0], item[2]),
            [heappop(scored_items) for _ in range(min(len(scored_items), k))],
        )
    )

def annotate_pattern(
        query_type,
        query,
        dblp_file,
        title_file,
        author_file,
        n_context,
        n_synonyms,
        n_examples,
    ):
    matches = []
    query_match = None

    logging.info('Extracting patterns')

    # Extract the patterns from the input files.
    if query_type == 'author':
        query_match = get_author_match(query.lower())
    else:
        query = ' '.join(tokenize_title(query))
        query_match = get_title_match(query)

    query_match = add_matches(
        query_type == 'author',
        author_file,
        get_author_match,
        matches,
        query_match,
    )

    query_match = add_matches(
        query_type == 'title',
        title_file,
        get_title_match,
        matches,
        query_match,
    )

    logging.info('Matching patterns against XML dataset')

    # Match the patterns against the transaction XML dataset.
    def get_context():
        dblp_file.seek(0)

        return etree.iterparse(
            dblp_file,
            dtd_validation=True,
            events=('end',),
            tag='inproceedings',
            recover=True,
        )

    tid = 0
    for _, node in get_context():
        for match in [query_match] + matches:
            if match['test'](node):
                match['transactions'].add(tid)

        tid = tid + 1

    logging.info('Calculating the context scores')

    # Store the weights (mutual information) of the context units in a priority
    # queue and extract the k largest patterns.
    query_context = pick_largest_k(
        matches,
        lambda match: mutual_info(query_match, match, tid),
        n_context,
    )

    getContextUnit = lambda context: (
        context[0],
        {
            'pattern': context[1]['pattern'],
            'transactions': context[1]['transactions'],
        },
    )

    logging.debug('Context')
    logging.debug(list(map(getContextUnit, query_context)))

    # Store the context similarities (cosine similarity) of the context units in
    # a priority queue and extract the k largest patterns.

    query_syn = pick_largest_k(
        matches,
        lambda match: cosine_sim(
            np.array([score for score, _ in query_context]),
            np.array([
                mutual_info(match, context_match, tid)
                for _, context_match in query_context
            ]),
        ),
        n_synonyms,
    )

    logging.debug('Synonyms')
    logging.debug(list(map(getContextUnit, query_syn)))

    # Store the representative transactions of the query pattern in a sorted
    # list with restricted size.
    tid = 0
    query_examples = []

    for _, node in get_context():
        insort(
            query_examples,
            (
                -cosine_sim(
                    np.array([score for score, _ in query_context]),

                    # Original paper assigns 0 to non-matching patterns and 1 to
                    # matching patterns. I found that because Mutual Information
                    # tends to be small, it's much better to assign -1 and 1 for
                    # these respective cases.
                    np.array([
                        float(context_match['test'](node)) * 2 - 1
                        for _, context_match in query_context
                    ]),
                ),
                tid,
                {
                    'title' : node.find('title').text,
                    'authors' : list(
                        map(
                            lambda author_node: author_node.text,
                            node.findall('author'),
                        )
                    ),
                },
            ),
        )

        if len(query_examples) > n_examples:
            del query_examples[-1]

        tid = tid + 1

    logging.debug('Examples')
    logging.debug(query_examples)

    # Print the pattern with its semantic annotations
    definition_node = etree.Element("definition")

    query_match['serialize'](etree.SubElement(definition_node, "pattern"))

    context_node = etree.SubElement(definition_node, "context")
    for _, match in query_context:
        match['serialize'](etree.SubElement(context_node, "pattern"))

    synonyms_node = etree.SubElement(definition_node, "synonyms")
    for _, match in query_syn:
        match['serialize'](etree.SubElement(synonyms_node, "pattern"))

    examples_node = etree.SubElement(definition_node, "examples")
    for _, _, transaction in query_examples:
        transaction_node = etree.SubElement(examples_node, "transaction")

        title_node = etree.SubElement(transaction_node, 'title')
        title_node.text = transaction['title']

        for author in transaction['authors']:
            author_node = etree.SubElement(transaction_node, 'author')
            author_node.text = author

    print(etree.tostring(definition_node, pretty_print=True).decode())

if __name__ == '__main__':
    parser = ArgumentParser(
        description='Enrich patterns with semantic annotations.'
    )

    parser.add_argument(
        '--log',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        default='ERROR',
        help='the log level (Default: ERROR)',
    )
    parser.add_argument(
        '--title_file',
        required=True,
        help='REQUIRED: the input file that stores the patterns for titles',
    )
    parser.add_argument(
        '--author_file',
        required=True,
        help='REQUIRED: the input file that stores the patterns for authors',
    )
    parser.add_argument(
        '-q',
        '--query',
        required=True,
        help='REQUIRED: the query pattern to enrich with semantic annotations',
    )
    parser.add_argument(
        '--type',
        required=True,
        choices=['author', 'title'],
        help='REQUIRED: the type of the query pattern',
    )
    parser.add_argument(
        '-n1',
        '--n_context',
        type=int,
        required=True,
        help='REQUIRED: the number of context indicators to select',
    )
    parser.add_argument(
        '-n2',
        '--n_synonyms',
        type=int,
        required=True,
        help='REQUIRED: the number of semantically similar patterns to select',
    )
    parser.add_argument(
        '-n3',
        '--n_examples',
        type=int,
        required=True,
        help='REQUIRED: the number of representative transactions to select',
    )
    parser.add_argument(
        'dblp_file',
        help='REQUIRED: the XML input file with all the transactions',
    )

    args = parser.parse_args()

    numeric_level = getattr(logging, args.log.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError('Invalid log level: %s' % loglevel)

    logging.basicConfig(level=numeric_level)

    # Download meta-files required by the tokenizer library.
    nltk.download('punkt', quite=True)
    nltk.download('stopwords', quite=True)

    dblp_file = open(args.dblp_file, 'rb')
    title_file = open(args.title_file, 'r')
    author_file = open(args.author_file, 'r')

    try:
        annotate_pattern(
            args.type,
            args.query,
            dblp_file,
            title_file,
            author_file,
            args.n_context,
            args.n_synonyms,
            args.n_examples,
        )

    finally:
        dblp_file.close()
        title_file.close()
        author_file.close()
