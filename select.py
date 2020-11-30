from argparse import ArgumentParser
from krovetz import PyKrovetzStemmer
from lxml import etree
import nltk
from nltk import word_tokenize
from os import mkdir
from pathlib import Path
from pygtrie import CharTrie
from re import fullmatch
from shutil import copyfileobj, rmtree
from string import punctuation

def get_article(node, stemmer, journal_filter):
    if node.tag != 'article':
        return None

    journal_node = node.find('journal')
    if journal_node is None:
        return None

    journal = journal_node.text
    if journal_filter is not None:
        if journal is None:
            return None

        if journal.lower().find(journal_filter.lower()) == -1:
            return None

    title_node = node.find('title')
    if title_node is None:
        return None

    # Tokenize and stem words as indicated in the original paper.
    # Remove isolated puntuation marks but leave words that contain
    # non-alphabetic characters, e.g., "mr." or "can't".
    title = '' if title_node.text is None else title_node.text
    title = list(
        filter(
            lambda word: not fullmatch('[' + punctuation + ']+', word),
            map(stemmer.stem, word_tokenize(title))
        )
    )

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
        'title': title,
        'original_title': title_node.text,
        'authors': authors,
    }

def list_articles(context, journal_filter):
    stemmer = PyKrovetzStemmer()

    for _, node in context:
        article = get_article(node, stemmer, journal_filter)
        if article is not None:
            yield article

        # It's safe to call clear() here because no descendants will be accessed
        node.clear()

        # Also eliminate now-empty references from the root node.
        for ancestor in node.xpath('ancestor-or-self::*'):
            while ancestor.getprevious() is not None:
                del ancestor.getparent()[0]

def get_article_node(article):
    article_node = etree.Element('article')

    title_node = etree.SubElement(article_node, 'title')
    title_node.text = ' '.join(article['title'])

    original_title_node = etree.SubElement(article_node, 'original-title')
    original_title_node.text = article['original_title']

    author_node = etree.SubElement(article_node, 'authors')
    author_node.text = ' ; '.join(article['authors'])

    return article_node

if __name__ == '__main__':
    parser = ArgumentParser(description='Select DBLP articles for SPMF mining.')
    parser.add_argument(
        '-j', '--journal', help='select articles only from such journals'
    )
    parser.add_argument(
        'input_dblp',
        nargs='?',
        default='dblp.xml',
        help='the path to the DBLP input file (default: dblp.xml)',
    )

    args = parser.parse_args()

    # Download meta-files required by the tokenizer library.
    nltk.download('punkt')

    # Filter articles from the DBLP XML database.
    print('# Filtering articles from the DBLP XML database.')

    context = etree.iterparse(
        args.input_dblp,
        dtd_validation=True,
        events=('start', 'end'),
        recover=True,
    )

    authors = CharTrie()
    title_words = CharTrie()

    if Path('.tmp').exists():
        rmtree('.tmp')
    mkdir('.tmp')

    title_db_file = open('.tmp/titles_db.spmf', 'w+')
    author_db_file = open('.tmp/authors_db.spmf', 'w+')

    try:
        author_id = 1
        title_wid = 1
        article_count = 0

        with etree.xmlfile('articles.xml', encoding='utf-8') as db_file:
            db_file.write_declaration(standalone=True)

            with db_file.element('dblp'):
                for article in list_articles(context, args.journal):
                    db_file.write(get_article_node(article))

                    # Assign a new ID to every newly seen author.
                    for author in article['authors']:
                        if author in authors:
                            continue

                        authors[author] = author_id
                        author_id = author_id + 1

                    # Assign a new ID to every newly seen word from each title.
                    for word in article['title']:
                        if word in title_words:
                            continue

                        title_words[word] = title_wid
                        title_wid = title_wid + 1

                    # Write title sequences and author itemset in SPMF format.
                    title_seq = map(
                        lambda word: str(title_words[word]), article['title']
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
    print('# Writing author itemsets and title sequences in SPMF format.')

    title_file = open('titles.spmf', 'w+')
    author_file = open('authors.spmf', 'w+')

    title_db_file = open('.tmp/titles_db.spmf', 'r')
    author_db_file = open('.tmp/authors_db.spmf', 'r')

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
        title_file.close()
        title_db_file.close()

        author_file.close()
        author_db_file.close()

    rmtree(Path('.tmp'))

    print('{} articles selected.'.format(article_count))
