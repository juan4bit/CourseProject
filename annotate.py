from argparse import ArgumentParser
from bisect import insort
from heapq import heapify, heappop
from itertools import product
from krovetz import PyKrovetzStemmer
from lxml import etree
import math
from nltk import word_tokenize
import numpy as np
from re import fullmatch
from string import punctuation

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
            pattern, node.find('title').text.split()
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
            node.find('authors').text.split(sep=' ; ')
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
    return np.dot(a, b) / (a_norm * b_norm)

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

    return sum([
        p_ab[x][y] * math.log2(p_ab[x][y] / (p_a[x] * p_b[y]))
        for x, y in product([0, 1], [0, 1])
    ])

if __name__ == '__main__':
    parser = ArgumentParser(
        description='Enrich patterns with semantic annotations.'
    )
    parser.add_argument(
        '-a',
        '--author_file',
        required=True,
        help='REQUIRED: the input file that stores the patterns for authors',
    )
    parser.add_argument(
        '-t',
        '--title_file',
        required=True,
        help='REQUIRED: the input file that stores the patterns for titles',
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
        '-k1',
        '--k_context',
        type=int,
        required=True,
        help='REQUIRED: the number of context indicators to select',
    )
    parser.add_argument(
        '-k2',
        '--k_synonyms',
        type=int,
        required=True,
        help='REQUIRED: the number of semantically similar patterns to select',
    )
    parser.add_argument(
        '-k3',
        '--k_examples',
        type=int,
        required=True,
        help='REQUIRED: the number of representative transactions to select',
    )
    parser.add_argument(
        'input_db',
        help='REQUIRED: the XML input file with all the transactions',
    )

    args = parser.parse_args()

    matches = []
    query_match = None

    # Extract the patterns from the input files.
    if args.type == 'author':
        query_match = get_author_match(args.query.lower())
    else:
        stemmer = PyKrovetzStemmer()
        query = ' '.join(
            filter(
                lambda word: not fullmatch('[' + punctuation + ']+', word),
                map(stemmer.stem, word_tokenize(args.query))
            )
        )
        query_match = get_title_match(query)

    with open(args.author_file, 'r') as author_file:
        query_match = add_matches(
            args.type == 'author',
            author_file,
            get_author_match,
            matches,
            query_match,
        )

    with open(args.title_file, 'r') as title_file:
        query_match = add_matches(
            args.type == 'title',
            title_file,
            get_title_match,
            matches,
            query_match,
        )

    # Match the patterns against the transaction XML database.
    def get_context():
        return etree.iterparse(
            args.input_db,
            dtd_validation=True,
            events=('end',),
            tag='article',
            recover=True,
        )

    tid = 0
    for _, node in get_context():
        for match in [query_match] + matches:
            if match['test'](node):
                match['transactions'].add(tid)

        tid = tid + 1

    # Store the weights (mutual information) of the context units in a priority
    # queue and extract the k largest patterns.
    scored_matches = [
        (-mutual_info(query_match, match, tid), ix, match)
        for ix, match in enumerate(matches)
    ]
    heapify(scored_matches)

    query_context = [heappop(scored_matches) for _ in range(args.k_context)]

    # Store the context similarities (cosine similarity) of the context units in
    # a priority queue and extract the k largest patterns.
    scored_contexts = [
        (
            -cosine_sim(
                np.array([-score for score, _, _ in query_context]),
                np.array([
                    mutual_info(match, context_match, tid)
                    for _, _, context_match in query_context
                ]),
            ),
            ix,
            match,
        )
        for ix, match in enumerate(matches)
    ]
    heapify(scored_contexts)

    query_syn = [heappop(scored_contexts) for _ in range(args.k_synonyms)]

    # Store the representative transactions of the query pattern in a sorted
    # list with restricted size.
    tid = 0
    query_examples = []
    for _, node in get_context():
        insort(
            query_examples,
            (
                -cosine_sim(
                    np.array([-score for score, _, _ in query_context]),
                    np.array([
                        float(context_match['test'](node))
                        for _, _, context_match in query_context
                    ]),
                ),
                tid,
                {
                    'title' : node.find('original-title').text,
                    'authors' : node.find('authors').text.split(sep=' ; '),
                },
            ),
        )

        if len(query_examples) > args.k_examples:
            del query_examples[-1]

        tid = tid + 1

    # Print the pattern with its semantic annotations

    definition_node = etree.Element("definition")

    query_match['serialize'](etree.SubElement(definition_node, "pattern"))

    context_node = etree.SubElement(definition_node, "context")
    for _, _, match in query_context:
        match['serialize'](etree.SubElement(context_node, "pattern"))

    synonyms_node = etree.SubElement(definition_node, "synonyms")
    for _, _, match in query_syn:
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
