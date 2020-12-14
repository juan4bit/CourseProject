import annotate
from argparse import ArgumentTypeError, ArgumentParser
from compress import compress_patterns
import logging
import nltk
from os import remove
from pathlib import Path
import scrape
import subprocess
from tempfile import NamedTemporaryFile, TemporaryFile

def restricted_float(x):
    try:
        x = float(x)

    except ValueError:
        raise ArgumentTypeError("%r not a floating-point literal" % (x,))

    if x < 0.0 or x > 1.0:
        raise ArgumentTypeError("%r not in range [0.0, 1.0]" % (x,))

    return x

def mine_patterns(
        mining_method,
        spmf_path,
        output_path,
        support,
        cleanup_re,
        dblp_file,
        tag,
        jaccard_threshold,
        is_sequence,
        separator,
    ):
    fp_file = NamedTemporaryFile(delete=False)
    fp_file.close()

    subprocess.run([
        'java',
        '-Xmx2048m',
        '-jar',
        './lib/spmf.jar',
        'run',
        mining_method,
        spmf_path,
        fp_file.name,
        str(support),
    ])

    subprocess.run(['sed', '-i', cleanup_re, fp_file.name])

    fp_file = open(fp_file.name, 'r')
    output_file = open(output_path, 'w+')

    try:
        compress_patterns(
            dblp_file,
            fp_file,
            output_file,
            tag,
            jaccard_threshold,
            is_sequence,
            separator,
        )

    finally:
        fp_file.close()
        output_file.close()

    remove(fp_file.name)

def scrape_patterns(args):
    # Download meta-files required by the tokenizer library.
    nltk.download('punkt', quiet=True)
    nltk.download('stopwords', quiet=True)

    dblp_file = open(args.dblp_file, 'rb')
    article_file = open(args.article_file, 'w+b')

    try:
        scrape.filter_articles(
            dblp_file,
            article_file,
            int(args.from_year) if args.from_year else None,
        )

    finally:
        dblp_file.close()
        article_file.close()

def mine_dblp_patterns(args):
    dblp_file = open(args.dblp_file, 'rb')
    title_spmf_file = NamedTemporaryFile(mode = 'w+', delete=False)
    author_spmf_file = NamedTemporaryFile(mode = 'w+', delete=False)

    try:
        scrape.mine_patterns(dblp_file, title_spmf_file, author_spmf_file)

    finally:
        dblp_file.close()
        title_spmf_file.close()
        author_spmf_file.close()

    with open(args.dblp_file, 'rb') as dblp_file:
        mine_patterns(
            'CloSpan',
            title_spmf_file.name,
            args.title_file,
            args.title_support,
            's/  / /g; s/ #SUP: [0-9]\+//g',
            dblp_file,
            'label',
            args.title_distance,
            True,
            ' ',
        )

    with open(args.dblp_file, 'rb') as dblp_file:
        mine_patterns(
            'FPClose',
            author_spmf_file.name,
            args.author_file,
            args.author_support,
            's/ \; #SUP: [0-9]\+//g',
            dblp_file,
            'author',
            args.author_distance,
            False,
            ' ; ',
        )

    remove(title_spmf_file.name)
    remove(author_spmf_file.name)

def annotate_pattern(args):
    dblp_file = open(args.dblp_file, 'rb')
    title_file = open(args.title_file, 'r')
    author_file = open(args.author_file, 'r')

    try:
        annotate.annotate_pattern(
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

if __name__ == '__main__':
    parser = ArgumentParser(
        description='Semantic annotations for DBLP patterns.'
    )

    parser.add_argument(
        '--log',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        default='ERROR',
        help='the log level (Default: ERROR)',
    )

    subparsers = parser.add_subparsers(dest='cmd')
    subparsers.required = True

    scrape_parser = subparsers.add_parser(
        'scrape', help='Scrape inproceeding articles from a DBLP dataset.'
    )

    scrape_parser.add_argument(
        '--dblp_file',
        required=True,
        help='REQUIRED: the path to the DBLP input file',
    )
    scrape_parser.add_argument(
        '--article_file',
        required=True,
        help='REQUIRED: the path where the selected articles will be printed in XML format',
    )
    scrape_parser.add_argument(
        '--from_year',
        help='selects articles from no earlier than the provided year',
    )

    scrape_parser.set_defaults(func=scrape_patterns)

    mine_parser = subparsers.add_parser(
        'mine', help='Mine author and title patterns from a DBLP dataset.'
    )

    mine_parser.add_argument(
        '--dblp_file',
        required=True,
        help='REQUIRED: the path to the DBLP input file',
    )
    mine_parser.add_argument(
        '--title_file',
        required=True,
        help='REQUIRED: the path where the title patterns will be printed',
    )
    mine_parser.add_argument(
        '--author_file',
        required=True,
        help='REQUIRED: the path where the author patterns will be printed',
    )
    mine_parser.add_argument(
        '--title_support',
        type=restricted_float,
        required=True,
        help='REQUIRED: the minimum support [0, 1] for title patterns.',
    )
    mine_parser.add_argument(
        '--author_support',
        type=restricted_float,
        required=True,
        help='REQUIRED: the minimum support [0, 1] for author patterns.',
    )
    mine_parser.add_argument(
        '--title_distance',
        type=restricted_float,
        required=True,
        help='REQUIRED: the Jaccard threshold [0, 1] to use when compressing title patterns',
    )
    mine_parser.add_argument(
        '--author_distance',
        type=restricted_float,
        required=True,
        help='REQUIRED: the Jaccard threshold [0, 1] to use when compressing author patterns',
    )

    mine_parser.set_defaults(func=mine_dblp_patterns)

    annotate_parser = subparsers.add_parser(
        'annotate', help='Enrich patterns with semantic annotations.'
    )

    annotate_parser.add_argument(
        '--dblp_file',
        required=True,
        help='REQUIRED: the XML input file with all the transactions',
    )
    annotate_parser.add_argument(
        '--title_file',
        required=True,
        help='REQUIRED: the input file that stores the patterns for titles',
    )
    annotate_parser.add_argument(
        '--author_file',
        required=True,
        help='REQUIRED: the input file that stores the patterns for authors',
    )
    annotate_parser.add_argument(
        '-q',
        '--query',
        required=True,
        help='REQUIRED: the query pattern to enrich with semantic annotations',
    )
    annotate_parser.add_argument(
        '--type',
        required=True,
        choices=['author', 'title'],
        help='REQUIRED: the type of the query pattern',
    )
    annotate_parser.add_argument(
        '-n1',
        '--n_context',
        type=int,
        required=True,
        help='REQUIRED: the number of context indicators to select',
    )
    annotate_parser.add_argument(
        '-n2',
        '--n_synonyms',
        type=int,
        required=True,
        help='REQUIRED: the number of semantically similar patterns to select',
    )
    annotate_parser.add_argument(
        '-n3',
        '--n_examples',
        type=int,
        required=True,
        help='REQUIRED: the number of representative transactions to select',
    )

    annotate_parser.set_defaults(func=annotate_pattern)

    args = parser.parse_args()

    numeric_level = getattr(logging, args.log.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError('Invalid log level: %s' % loglevel)

    logging.basicConfig(level=numeric_level)

    args.func(args)
