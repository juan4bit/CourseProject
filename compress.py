from argparse import ArgumentParser
from lxml import etree
import logging
import numpy as np

def restricted_float(x):
    try:
        x = float(x)

    except ValueError:
        raise ArgumentTypeError("%r not a floating-point literal" % (x,))

    if x < 0.0 or x > 1.0:
        raise ArgumentTypeError("%r not in range [0.0, 1.0]" % (x,))

    return x

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

def read_patterns(input_file, separator):
    for pattern in input_file:
        yield pattern.rstrip('\n').split(sep=separator)

def compress_patterns(
        db_file,
        input_file,
        output_file,
        tag,
        jaccard_threshold,
        is_sequence,
        separator
    ):
    logging.info('Extracting the patterns.')

    # Extract the patterns.
    matches = list(
        map(
            lambda pattern: { 'pattern' : pattern, 'transactions' : set() },
            read_patterns(input_file, separator)
        )
    )

    logging.debug('Patterns')
    logging.debug(list(map(lambda match: match['pattern'], matches)))

    # Compute pattern matching against XML database.
    logging.info('Computing pattern matching against XML database.')

    context = etree.iterparse(
        db_file,
        dtd_validation=True,
        events=('end',),
        recover=True,
    )

    tid = 0
    for _, node in context:
        if node.tag != 'inproceedings':
            continue

        item_list = list(
            map(
                lambda node: node.text,
                filter(
                    lambda node: node is not None and node.text is not None,
                    node.findall(tag),
                ),
            )
        )

        if not item_list:
            continue

        for match in matches:
            # Check for subsequence match in case of sequential patterns.
            if is_sequence:
                transaction = item_list[0].split(sep=separator)

                if not is_subsequence(match['pattern'], transaction):
                    continue

                logging.debug(
                    'Pattern {} matched {}'.format(
                        match['pattern'], transaction
                    )
                )

            # Check for subset match in case of itemset patterns.
            elif not set(match['pattern']).issubset(item_list):
                continue
            else:
                logging.debug(
                    'Pattern {} matched {}'.format(match['pattern'], item_list)
                )

            match['transactions'].add(tid)

        tid = tid + 1

    # Compute pattern distances.
    logging.info('Computing pattern distances.')

    # For each pattern, calculate its Jaccard distance to the other patterns.
    jaccard_matrix = np.zeros((len(matches), len(matches)))
    for rowIx in range(len(matches)):
        for colIx in range(rowIx):
            tA = matches[rowIx]['transactions']
            tB = matches[colIx]['transactions']

            logging.debug('Pattern {}'.format(matches[rowIx]['pattern']))
            logging.debug(tA)

            logging.debug('Pattern {}'.format(matches[colIx]['pattern']))
            logging.debug(tB)

            # Jaccard Distance = 1 - | Da ^ Db | / | Da v Db |
            # where Da and Db are the transactions pattern A and B occur
            # respectively.
            distance = 1 - len(tA.intersection(tB)) / len(tA.union(tB))
            jaccard_matrix[rowIx, colIx] = distance

    # Because distances are symmetric, only calculate the lower triangle of the
    # distance matrix and populate the upper triangle by forcing symmetry.
    jaccard_matrix = jaccard_matrix + jaccard_matrix.T

    logging.debug('Jaccardian matrix')
    logging.debug(jaccard_matrix)

    # Compute clusters.
    logging.info('Computing clusters.')

    clusters = []

    # For each pattern:
    for matchIx in range(len(matches)):
        # If there are no previous clusters, create one for the current pattern.
        if not clusters:
            clusters.append([matchIx])
            continue

        minCluster = None
        minDistance = None

        # Calculate the distance to the closest cluster for the current pattern
        # and return the cluster and distance.
        for cluster in clusters:
            # The distance to a cluster is determined by the Jaccard distance
            # between the current pattern and the farthest pattern in the
            # cluster, that is, complete linkage.
            distance = max(jaccard_matrix[matchIx, cluster])

            if minDistance is None or distance < minDistance:
                minDistance = distance
                minCluster = cluster

        # If the distance to the closest cluster is less than a threshold,
        # assign the pattern to the cluster.
        if minDistance < jaccard_threshold:
            minCluster.append(matchIx)

        # Else create a new cluster for the pattern.
        else:
            clusters.append([matchIx])

    logging.debug('Clusters')
    logging.debug(clusters)
    logging.debug(
        list(
            map(
                lambda cluster: (
                    [matches[matchIx]['pattern'] for matchIx in cluster]
                ),
                clusters,
            )
        )
    )

    # Write every cluster medoid as a compressed pattern.
    logging.info('Writing every cluster medoid as a compressed pattern.')

    # For each cluster:
    for cluster in clusters:
        # Get the pattern that is closest to the 'center' of the cluster.
        medoid = matches[
            min(
                map(
                    lambda matchIx: {
                        'matchIx' : matchIx,

                        # The distance to a cluster's center is determined
                        # by the average distance of each pattern to others
                        # in the same cluster.
                        'distance' : np.average(
                            jaccard_matrix[matchIx, cluster]
                        ),
                    },
                    cluster,
                ),
                key=lambda match: match['distance'],
            )['matchIx']
        ]

        pattern = separator.join(medoid['pattern'])
        output_file.write('{}\n'.format(pattern))

    logging.info(
        '{} out of {} patterns selected.'.format(len(clusters), len(matches))
    )

    compression_rate = 0
    if len(matches) != 0:
        compression_rate = (len(matches) - len(clusters)) / len(matches) * 100

    logging.info('{:.2f}% compression rate.'.format(compression_rate))

if __name__ == '__main__':
    parser = ArgumentParser(description='Remove pattern redundancy.')

    parser.add_argument(
        '--log',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        default='ERROR',
        help='the log level (Default: ERROR)',
    )
    parser.add_argument(
        '-i',
        '--input_file',
        required=True,
        help='REQUIRED: the input file that stores the uncompressed patterns',
    )
    parser.add_argument(
        '-o',
        '--output_file',
        required=True,
        help='REQUIRED: the output file that will store the compressed patterns',
    )
    parser.add_argument(
        '-t',
        '--tag',
        required=True,
        help='REQUIRED: the tag to search for in the XML database',
    )
    parser.add_argument(
        '-d',
        '--distance',
        required=True,
        type=restricted_float,
        help='REQUIRED: the Jaccard distance threshold for every cluster of patterns',
    )
    parser.add_argument(
        '--sequence',
        action='store_true',
        help='whether patterns are sequences or not (default: False)',
    )
    parser.add_argument(
        '--separator',
        default=' ',
        help='the string separating items in a transaction (default: <SPACE>)',
    )
    parser.add_argument(
        'db_file', help='the XML input file with all the transactions'
    )

    args = parser.parse_args()

    numeric_level = getattr(logging, args.log.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError('Invalid log level: %s' % loglevel)

    logging.basicConfig(level=numeric_level)

    db_file = open(args.db_file, 'rb')
    input_file = open(args.input_file, 'r')
    output_file = open(args.output_file, 'w+')

    try:
        compress_patterns(
            db_file,
            input_file,
            output_file,
            args.tag,
            args.distance,
            args.sequence,
            args.separator
        )

    finally:
        db_file.close()
        input_file.close()
        output_file.close()
