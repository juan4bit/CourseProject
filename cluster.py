from argparse import ArgumentParser
from lxml import etree
import numpy as np

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

def read_patterns(pattern_file, separator):
    for pattern in pattern_file:
        yield pattern.rstrip('\n').split(sep=separator)

if __name__ == '__main__':
    parser = ArgumentParser(description='Remove pattern redundancy.')
    parser.add_argument(
        '-i',
        '--input',
        required=True,
        help='REQUIRED: the input file that stores the uncompressed patterns',
    )
    parser.add_argument(
        '-o',
        '--output',
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
        type=float,
        required=True,
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
        'input_db', help='the XML input file with all the transactions'
    )

    args = parser.parse_args()

    # Extract the patterns.
    print('# Extracting the patterns.')

    matches = []
    with open(args.input, 'r') as pattern_file:
        matches = list(
            map(
                lambda pattern: { 'pattern' : pattern, 'transactions' : set() },
                read_patterns(pattern_file, args.separator)
            )
        )

    # Compute pattern matching against XML database.
    print('# Computing pattern matching against XML database.')

    context = etree.iterparse(
        args.input_db,
        dtd_validation=True,
        events=('end',),
        tag=args.tag,
        recover=True,
    )

    tid = 0
    for _, node in context:
        if node.text is None:
            continue

        for match in matches:
            transaction = node.text.split(sep=args.separator)

            # Check for subsequence match in case of sequential patterns.
            if args.sequence:
                if not is_subsequence(match['pattern'], transaction):
                    continue

            # Check for subset match in case of itemset patterns.
            elif not set(match['pattern']).issubset(transaction):
                continue

            match['transactions'].add(tid)

        tid = tid + 1

    # Compute pattern distances.
    print('# Computing pattern distances.')

    # For each pattern, calculate its Jaccard distance to the other patterns.
    jaccard_matrix = np.zeros((len(matches), len(matches)))
    for rowIx in range(len(matches)):
        for colIx in range(rowIx):
            tA = matches[rowIx]['transactions']
            tB = matches[colIx]['transactions']

            # Jaccard Distance = 1 - | Da ^ Db | / | Da v Db |
            # where Da and Db are the transactions pattern A and B occur
            # respectively.
            distance = 1 - len(tA.intersection(tB)) / len(tA.union(tB))
            jaccard_matrix[rowIx, colIx] = distance

    # Because distances are symmetric, only calculate the lower triangle of the
    # distance matrix and populate the upper triangle by forcing symmetry.
    jaccard_matrix = jaccard_matrix + jaccard_matrix.T

    # Compute clusters.
    print('# Computing clusters.')

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
        if minDistance < args.distance:
            minCluster.append(matchIx)

        # Else create a new cluster for the pattern.
        else:
            clusters.append([matchIx])

    # Write every cluster medoid as a compressed pattern.
    print('# Writing every cluster medoid as a compressed pattern.')

    with open(args.output, 'w+') as output_file:
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

            pattern = args.separator.join(medoid['pattern'])
            output_file.write('{}\n'.format(pattern))

    print('{} out of {} patterns selected.'.format(len(clusters), len(matches)))
    print(
        '{:.2f}% compression rate.'.format(
            (len(matches) - len(clusters)) / len(matches) * 100
        )
    )
