from argparse import ArgumentParser
from krovetz import PyKrovetzStemmer
from lxml import etree
import logging
import nltk
from nltk import corpus, word_tokenize
from os import remove
from pathlib import Path
from pygtrie import CharTrie
from re import fullmatch
from shutil import copyfileobj
from string import punctuation
from tempfile import NamedTemporaryFile

def tokenize_title(title):
    stemmer = PyKrovetzStemmer()
    stop_words = set(corpus.stopwords.words('english'))

    def is_title_term(word):
        return not (
            fullmatch('[' + punctuation + ']+', word) or word in stop_words
        )

    return list(
        filter(is_title_term, map(stemmer.stem, word_tokenize(title)))
    )

def get_article(node, from_year):
    if node.tag != 'inproceedings':
        return None

    year = None
    year_node = node.find('year')
    if year_node is not None and year_node.text is not None:
        year = int(year_node.text)

    if from_year is not None and (year is None or year < from_year):
        return None

    title_node = node.find('title')
    if title_node is None:
        return None

    # Tokenize and stem words as indicated in the original paper then remove
    # stop words and isolated puntuation marks but leave words that contain
    # non-alphabetic characters, e.g., "mr." or "can't".
    title = '' if title_node.text is None else title_node.text
    title = tokenize_title(title)

    if not title:
        return None

    authors = []
    for author_node in node.findall('author'):
        if author_node is None:
            continue

        # Remove the numbers that show up along author names from the original
        # database, e.g. "0001".
        author = '' if author_node.text is None else author_node.text
        author = ' '.join(
            filter(
                lambda word: not fullmatch('[0-9' + punctuation + ']+', word),
                word_tokenize(author.lower())
            )
        )

        if author == '':
            continue

        authors.append(author)

    if not authors:
        return None

    return {
        'year': year,
        'label': title,
        'authors': authors,
        'title': title_node.text,
    }

def list_articles(context, journal_filter):
    for _, node in context:
        article = get_article(node, journal_filter)
        if article is not None:
            yield article

        # It's safe to call clear() here because no descendants will be accessed
        node.clear()

        # Also eliminate now-empty references from the root node.
        for ancestor in node.xpath('ancestor-or-self::*'):
            while ancestor.getprevious() is not None:
                del ancestor.getparent()[0]

def get_article_node(article):
    article_node = etree.Element('inproceedings')

    title_node = etree.SubElement(article_node, 'title')
    title_node.text = article['title']

    if article['year'] is not None:
        year_node = etree.SubElement(article_node, 'year')
        year_node.text = str(article['year'])

    label_node = etree.SubElement(article_node, 'label')
    label_node.text = ' '.join(article['label'])

    for author in article['authors']:
        author_node = etree.SubElement(article_node, 'author')
        author_node.text = author

    return article_node

def filter_articles(dblp_file, article_file, from_year):
    logging.info('Filtering articles from the DBLP XML database.')

    context = etree.iterparse(
        dblp_file,
        dtd_validation=True,
        events=('start', 'end'),
        recover=True,
    )

    article_count = 0

    # Filter articles from the DBLP XML database.
    with etree.xmlfile(article_file, encoding='utf-8') as db_file:
        db_file.write_declaration(standalone=True)

        with db_file.element('dblp'):
            for article in list_articles(context, from_year):
                db_file.write(get_article_node(article))

            article_count = article_count + 1

    logging.info('{} articles written.'.format(article_count))

def mine_patterns(dblp_file, title_file, author_file):
    logging.info(
        'Writing author itemsets and title sequences in SPMF format.'
    )

    context = etree.iterparse(
        dblp_file,
        dtd_validation=True,
        events=('start', 'end'),
        recover=True,
    )

    authors = CharTrie()
    title_words = CharTrie()

    title_db_file = NamedTemporaryFile(mode = 'w+', delete=False)
    author_db_file = NamedTemporaryFile(mode = 'w+', delete=False)

    try:
        author_id = 1
        title_wid = 1
        article_count = 0

        # For each article in the dataset:
        for article in list_articles(context, None):
            # Assign a new ID to every newly seen author.
            for author in article['authors']:
                if author in authors:
                    continue

                authors[author] = author_id
                author_id = author_id + 1

            # Assign a new ID to every newly seen word from each title.
            for word in article['label']:
                if word in title_words:
                    continue

                title_words[word] = title_wid
                title_wid = title_wid + 1

            # Write title sequences and author itemset in SPMF format.
            title_seq = map(
                lambda word: str(title_words[word]), article['label']
            )
            title_db_file.write(' -1 '.join(title_seq) + ' -2\n')

            author_set = map(
                lambda author: str(authors[author]), article['authors']
            )
            author_db_file.write(' '.join(author_set) + '\n')

            article_count = article_count + 1

    finally:
        title_db_file.close()
        author_db_file.close()

    # Add the conversion header to the SPMF files for author itemsets and title
    # sequences.
    title_db_file = open(title_db_file.name, 'r')
    author_db_file = open(author_db_file.name, 'r')

    try:
        title_file.write('@CONVERTED_FROM_TEXT\n')
        title_file.write('@ITEM=-1=\n')
        for (word, wid) in title_words.iteritems():
            title_file.write('@ITEM={}={}\n'.format(str(wid), word))
        copyfileobj(title_db_file, title_file)

        author_file.write('@CONVERTED_FROM_TEXT\n')
        for (author, aid) in authors.iteritems():
            author_file.write('@ITEM={}={} ;\n'.format(str(aid), author))
        copyfileobj(author_db_file, author_file)

    finally:
        title_db_file.close()
        author_db_file.close()

    remove(title_db_file.name)
    remove(author_db_file.name)

    logging.info('{} articles written.'.format(article_count))

if __name__ == '__main__':
    parser = ArgumentParser(
        description='Transform DBLP articles for SPMF mining.'
    )

    parser.add_argument(
        '--log',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        default='ERROR',
        help='the log level (Default: ERROR)',
    )
    parser.add_argument(
        'dblp_file',
        nargs='?',
        default='dblp.xml',
        help='the path to the DBLP input file (default: dblp.xml)',
    )
    parser.add_argument(
        '--title_file',
        help='the path where the titles will be printed in SPMF format',
    )
    parser.add_argument(
        '--author_file',
        help='the path where the authors will be printed in SPMF format',
    )

    args = parser.parse_args()

    numeric_level = getattr(logging, args.log.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError('Invalid log level: %s' % loglevel)

    logging.basicConfig(level=numeric_level)

    dblp_file = open(args.dblp_file, 'rb')
    title_file = open(args.title_file, 'w+')
    author_file = open(args.author_file, 'w+')

    try:
        mine_patterns(args.dblp_file, title_file, author_file)

    finally:
        dblp_file.close()
        title_file.close()
        author_file.close()
