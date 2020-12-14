# Pattern annotation

## Table of Contents

<!-- vim-markdown-toc GFM -->

* [Introduction](#introduction)
* [Prerequisites](#prerequisites)
* [Installation](#installation)
* [Implementation](#implementation)
  * [Selecting DBLP inproceedings (conferences)](#selecting-dblp-inproceedings-conferences)
  * [Pattern extraction and compression](#pattern-extraction-and-compression)
  * [Semantic annotation](#semantic-annotation)
* [Tutorial](#tutorial)
  * [Selecting DBLP inproceedings (conferences)](#selecting-dblp-inproceedings-conferences-1)
  * [Pattern extraction and compression](#pattern-extraction-and-compression-1)
  * [Semantic annotation](#semantic-annotation-1)
* [Presentation](#presentation)

<!-- vim-markdown-toc -->

## Introduction

In this project I will try to reproduce the results of the following paper:
* Qiaozhu Mei, Dong Xin, Hong Cheng, Jiawei Han, and ChengXiang Zhai. 2006. Generating semantic annotations for frequent patterns with context analysis. In Proceedings of the 12th ACM SIGKDD international conference on Knowledge discovery and data mining (KDD 2006). ACM, New York, NY, USA, 337-346. DOI=10.1145/1150402.1150441

This paper proposes using paradigmatic and syntagmatic relationships from text data in order to annotate non-text data with semantic context in the same way a dictionary would define a word with synonyms (paradigmatic patterns) and examples of the word being used in a context (syntagmatic context).

In this particular implementation, the non-text data represents items from a transactional database, instantiated as authors from major computer conferences, and the text data represents the titles from such conferences.

## Prerequisites

You will need a Unix machine to run this tool, I used Ubuntu 20.04 at the time of developing and testing. You will also need to install [Python 3](https://www.python.org/downloads) and the latest [Java Runtime Environment](https://www.oracle.com/java/technologies/javase-jre8-downloads.html).

## Installation

> Clone the project from the code repository:
```sh
git clone https://github.com/juan4bit/CourseProject.git
cd CourseProject
```

> Once in the project folder, install the following Python dependencies:
```sh
python -m pip install -U pip wheel
```

> Optional: You may additionally want to setup a virtual environment for this project by running:
```sh
python -m venv ~/.envs/CourseProject
source ~/.envs/CourseProject/bin/activate
```

> Finally, install the following Python dependencies:
```sh
pip install -r requirements.txt
```

> And download the [SPMF tool](https://www.philippe-fournier-viger.com/spmf/index.php?link=download.php) and place the jar file in the *./lib* folder of the project directory. You may also need to give this file executable permissions:
```sh
chmod +x spmf.jar
```

## Implementation

I decided to implement this paper in three stages that I describe in detail below.

### Selecting DBLP inproceedings (conferences)

The original paper tests the algorithm by selecting a subset of conferences from the [DBLP](https://dblp.org) dataset, a 3GB+ XML file with bibliographic entries on major computer science journals, theses and proceedings. For the purpose of this paper, we are only interested on the proceedings (conferences). Furthermore, because the amount of conferences is too large, I also decided to select only those falling in a given date range (determined by year).

There are existing tools to manipulate and filter XML files, namely XSL templates, but because of the large size of the original DBLP dataset, I was not able to get any of them working so instead I decided to implement my own script which incrementally reads the DBLP file and selects only the items and fields I'm interested in, that is, the conference titles and its authors. Additionally, I also preprocess the title text through stemming and removal of stop words as described in the original paper.

This stage can be run via the `python main.py scrape` command which I will explain how to use in the next section.

### Pattern extraction and compression

Before extracting paradigmatic and syntagmatic relationships, we first need to mine patterns from the non-text data (authors) and text data (titles). The paper suggests using FP-Close algorithm for the former and CloSpan for the latter which instead of implementing them myself I decided to use a third party tool, SPMF, that I call internally from my script code, please make sure the dependency is installed as described in the previous section.

After the Closed Frequent Patterns are extracted, the paper suggests two compression algorithms to reduce the overall number of entries for future stages in the pipeline, aiming to reduce redundancy among the patterns in each dataset. I decided to implement one of the algorithms, One-pass Microclustering, where you calculate the [Jaccardian distance](https://en.wikipedia.org/wiki/Jaccard_index) between each pair of patterns in a given dataset and one by one, it starts to either append a pattern to an existing cluster if the Jaccardian distance to the farthest item in the group falls below a threshold or creates a brand new cluster for the pattern.

From each cluster then I select the pattern that is, on average, closer to the other patterns in the group, that is, the medoid pattern.

This stage can be run via the `python main.py mine` command which I will explain how to use in the next section.

### Semantic annotation

Given a preprocessed DBLP dataset and a list of Frequent Patterns for conference authors and titles, the last stage of the pipeline is a script that expects a query pattern as input (either an author, a list of authors or a text phrase) and returns its:

* Syntagmatic context. Given the definition of Mutual Information ![Mutual Information](https://math.now.sh?from=I%28X%3BY%29%3D%5Csum_%7Bx%5Cepsilon%20X%7D%5Csum_%7By%5Cepsilon%20Y%7D%20P(x%2Cy)log%5Cfrac%7BP(x%2Cy)%7D%7BP(x)P(y)%7D), where *x* and *y* are binary variables that represent each whether a pattern shows up in the database or not and *P* represents either the single or joint probability of these events happening, the algorithm scores each pattern from the list against the query and selects the top N as its context. Mutual Information can be understood as the reduction of uncertainty from a pattern once another one (e.g. the query) is given, the more reduction, the more likely these two patterns are related.
* Paradigmatic patterns. Given the set of patterns determined in the previous step, the algorithm calculates vectors of Mutual Information scores from each pattern in the original list against the patterns from the query context. Then it computes the cosine similarity between these vectors and the one from the query context and selects the top N patterns as paradigmatic relations. The rationale is that if the context patterns from the query reduce uncertainty in a similar way for another pattern, then it's likely that these two patterns are similar given a context.
* Paradigmatic transactions. The last step is similar to the previous one except in how the context of a transaction is calculated. For each pattern of the query context, the algorithm checks whether it appears in a transaction or not, if it does then it scores 1, otherwise -1. The original paper assigns 0 for a non-match but in practice I found out this value didn't yield good results.

This stage can be run via the `python main.py annotate` command which I will explain how to use in the next section.

## Tutorial

As mentioned in the previous section, there are three stages in the pipeline that can be run as individual commands. The tool provides help messages when running `python main.py --help` or `python main.py cmd --help`, where *cmd* can be either *scrape*, *mine* or *annotate*. In this section, I'll explain in detail these help messages and provide examples but before you start, make sure to download the [DBLP dataset](https://dblp.org/xml) and unzip the XML file **together with its DTD definition file**.

### Selecting DBLP inproceedings (conferences)

Running `python main.py scrape --help` yields the following output:
```sh
usage: main.py scrape [-h] --dblp_file DBLP_FILE --article_file ARTICLE_FILE [--from_year FROM_YEAR]

optional arguments:
  -h, --help            show this help message and exit
  --dblp_file DBLP_FILE
                        REQUIRED: the path to the DBLP input file
  --article_file ARTICLE_FILE
                        REQUIRED: the path where the selected articles will be printed in XML format
  --from_year FROM_YEAR
                        selects articles from no earlier than the provided year
```

So you can select conferences from the DBLP dataset by running a command similar to this one:
```sh
python main.py scrape --dblp_file dblp.xml --article_file articles.xml --from_year 2010
```

This will read *dblp.xml*, select all inproceedings (conferences) no earlier than 2010 and print the preprocessed items in *articles.xml* in the following format:
```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<dblp>
    <inproceedings>
        <title>Fast multipoint evaluation and interpolation of polynomials in the LCH-basi
s over F</title>
        <year>2020</year>
        <label>fast multipoint evaluate interpolation polynomial lch-basis f</label>
        <author>axel mathieu-mahias</author>
        <author>michaël quisquater</author>
    </inproceedings>
    ...
</dblp>
```

The **title** field stores the original title of the conference while **label** stores its preprocessed version (after stemming and then removing stop words).

### Pattern extraction and compression

Running `python main.py mine --help` yields the following output:
```sh
usage: main.py mine [-h] --dblp_file DBLP_FILE --title_file TITLE_FILE --author_file AUTHOR_FILE --title_support TITLE_SUPPORT --author_support AUTHOR_SUPPORT
                    --title_distance TITLE_DISTANCE --author_distance AUTHOR_DISTANCE

optional arguments:
  -h, --help            show this help message and exit
  --dblp_file DBLP_FILE
                        REQUIRED: the path to the DBLP input file
  --title_file TITLE_FILE
                        REQUIRED: the path where the title patterns will be printed
  --author_file AUTHOR_FILE
                        REQUIRED: the path where the author patterns will be printed
  --title_support TITLE_SUPPORT
                        REQUIRED: the minimum support [0, 1] for title patterns.
  --author_support AUTHOR_SUPPORT
                        REQUIRED: the minimum support [0, 1] for author patterns.
  --title_distance TITLE_DISTANCE
                        REQUIRED: the Jaccard threshold [0, 1] to use when compressing title patterns
  --author_distance AUTHOR_DISTANCE
                        REQUIRED: the Jaccard threshold [0, 1] to use when compressing author patterns
```

So you can mine and compress patterns by running a command similar to this one:
```sh
python main.py mine --dblp_file articles.xml --title_file titles.txt --author_file authors.txt --title_support 0.003 --author_support 0.001 --title_distance 0.9 --author_distance 0.9
```

This will read a **preprocessed** DBLP dataset (it assumes a **label** field exists for each *inproceedings* element which is not the case in the original DBLP file) and print to *titles.txt* and *authors.txt* the list of titles and authors respectively that were mined as frequent patterns. Title subsequences (that's what CloSpan generates) will be space separated while author itemsets will be semicolon separated. Title and author support represent the coverage percentage that a pattern needs to exhibit to be considered frequent, in this case, a title subsequence needs to show up in 0.3% of the transactions and an author itemset 0.1%. Title and author distances are the Jaccardian threshold described in the previous section, used to compress the pattern list by removing redundancy, the larger the threshold, the more agressive the compression is.

### Semantic annotation

Running `python main.py annotate --help` yields the following output:
```sh
usage: main.py annotate [-h] --db_file DB_FILE --title_file TITLE_FILE --author_file AUTHOR_FILE -q QUERY --type {author,title} -n1 N_CONTEXT -n2 N_SYNONYMS -n3 N_EXAMPLES

optional arguments:
  -h, --help            show this help message and exit
  --db_file DB_FILE     REQUIRED: the XML input file with all the transactions
  --title_file TITLE_FILE
                        REQUIRED: the input file that stores the patterns for titles
  --author_file AUTHOR_FILE
                        REQUIRED: the input file that stores the patterns for authors
  -q QUERY, --query QUERY
                        REQUIRED: the query pattern to enrich with semantic annotations
  --type {author,title}
                        REQUIRED: the type of the query pattern
  -n1 N_CONTEXT, --n_context N_CONTEXT
                        REQUIRED: the number of context indicators to select
  -n2 N_SYNONYMS, --n_synonyms N_SYNONYMS
                        REQUIRED: the number of semantically similar patterns to select
  -n3 N_EXAMPLES, --n_examples N_EXAMPLES
                        REQUIRED: the number of representative transactions to select
```

So you can find the semantic annotations of a given query pattern by running a command similar to this one:
```sh
python main.py annotate --dblp_file articles.xml --title_file titles.txt --author_file authors.txt -q "network" --type title -n1 7 -n2 5 -n3 3
```

DBLP file, title file and author file paths point to the **preprocessed** DBLP dataset and the list of title and author patterns respectively. The query type can be either title or author, for the former just write any phrase surrounded by double quotes and for the latter write a semicolon-separated list of authors (casing doesn't matter but letter matching has to be identical so beware typos) also surrounded by quotes. N1, N2 and N3 represent the number of syntagmatic patterns and the number of paradigmatic patterns and transactions to retrieve respectively. The output will look something like the XML below:
```xml
<definition>
  <pattern>
    <title>network</title>
  </pattern>
  <context>
    <pattern>
      <title>deep neural</title>
    </pattern>
    <pattern>
      <title>convolution neural</title>
    </pattern>
    <pattern>
      <title>network image</title>
    </pattern>
    <pattern>
      <title>graph neural</title>
    </pattern>
    <pattern>
      <title>generative adversarial</title>
    </pattern>
    <pattern>
      <title>graph convolution</title>
    </pattern>
    <pattern>
      <title>network 3d</title>
    </pattern>
  </context>
  <synonyms>
    <pattern>
      <title>method</title>
    </pattern>
    <pattern>
      <title>optimize</title>
    </pattern>
    <pattern>
      <title>deep learning</title>
    </pattern>
    <pattern>
      <title>explore</title>
    </pattern>
    <pattern>
      <title>evaluate</title>
    </pattern>
  </synonyms>
  <examples>
    <transaction>
      <title>Dual-domain Deep Convolutional Neural Networks for Image Demoireing.</title>
      <author>vien gia an</author>
      <author>hyunkook park</author>
      <author>chul lee</author>
    </transaction>
    <transaction>
      <title>A topological encoding convolutional neural network for segmentation of 3D mu
ltiphoton images of brain vasculature using persistent homology.</title>
      <author>mohammad haft-javaherian</author>
      <author>martin villiger</author>
      <author>chris b. schaffer</author>
      <author>nozomi nishimura</author>
      <author>polina golland</author>
      <author>brett e. bouma</author>
    </transaction>
    <transaction>
      <title>FSNet: Compression of Deep Convolutional Neural Networks by Filter Summary.</
title>
      <author>yingzhen yang</author>
      <author>jiahui yu</author>
      <author>nebojsa jojic</author>
      <author>jun huan</author>
      <author>thomas s. huang</author>
    </transaction>
  </examples>
</definition>
```

## Presentation

You can find a recorded version of the tutorial [here](https://drive.google.com/file/d/1PmYx8yfq8m_jhEK9QStiHAKUvx0mLVvB/view?usp=sharing).
