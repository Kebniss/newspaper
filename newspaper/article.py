# -*- coding: utf-8 -*-
__title__ = 'newspaper'
__author__ = 'Lucas Ou-Yang'
__license__ = 'MIT'
__copyright__ = 'Copyright 2014, Lucas Ou-Yang'

import logging
import requests

from . import network
from . import urls

from .cleaners import DocumentCleaner
from .configuration import Configuration
from .extractors import ContentExtractor
from .outputformatters import OutputFormatter
from .utils import (URLHelper, RawHelper, extend_config)

log = logging.getLogger(__name__)


class ArticleDownloadState(object):
    NOT_STARTED = 0
    FAILED_RESPONSE = 1
    SUCCESS = 2


class ArticleException(Exception):
    pass


class Article(object):
    """Article objects abstract an online news article page
    """
    def __init__(self, url, title='', source_url='', config=None, **kwargs):
        """The **kwargs argument may be filled with config values, which
        is added into the config object
        """
        self.config = config or Configuration()
        self.config = extend_config(self.config, kwargs)

        self.extractor = ContentExtractor(self.config)

        if source_url == '':
            scheme = urls.get_scheme(url)
            if scheme is None:
                scheme = 'http'
            source_url = scheme + '://' + urls.get_domain(url)

        if source_url is None or source_url == '':
            raise ArticleException('input url bad format')

        # URL to the main page of the news source which owns this article
        self.source_url = source_url

        self.url = urls.prepare_url(url, self.source_url)

        # Body text from this article
        self.text = ''

        # This article's unchanged and raw HTML
        self.html = ''

        # The HTML of this article's main node (most important part)
        self.article_html = ''

        # Keep state for downloads and parsing
        self.is_parsed = False
        self.download_state = ArticleDownloadState.NOT_STARTED
        self.download_exception_msg = None

        # Holds the top element of the DOM that we determine is a candidate
        # for the main body of the article
        self.top_node = None

        # A deepcopied clone of the above object before heavy parsing
        # operations, useful for users to query data in the
        # "most important part of the page"
        self.clean_top_node = None

        # lxml DOM object generated from HTML
        self.doc = None

        # A deepcopied clone of the above object before undergoing heavy
        # cleaning operations, serves as an API if users need to query the DOM
        self.clean_doc = None


    def download(self, input_html=None, title=None, recursion_counter=0):
        """Downloads the link's HTML content, don't use if you are batch async
        downloading articles

        recursion_counter (currently 1) stops refreshes that are potentially
        infinite
        """
        if input_html is None:
            try:
                html = network.get_html_2XX_only(self.url, self.config)
            except requests.exceptions.RequestException as e:
                self.download_state = ArticleDownloadState.FAILED_RESPONSE
                self.download_exception_msg = str(e)
                log.debug('Download failed on URL %s because of %s' %
                          (self.url, self.download_exception_msg))
                return
        else:
            html = input_html

        self.set_html(html)

    def parse(self):
        self.throw_if_not_downloaded_verbose()

        self.doc = self.config.get_parser().fromstring(self.html)

        if self.doc is None:
            # `parse` call failed, return nothing
            return

        # TODO: Fix this, sync in our fix_url() method
        parse_candidate = self.get_parse_candidate()
        self.link_hash = parse_candidate.link_hash  # MD5

        document_cleaner = DocumentCleaner(self.config)
        output_formatter = OutputFormatter(self.config)

        # Before any computations on the body, clean DOM object
        doc = document_cleaner.clean(self.doc)

        text = ''
        top_node = self.extractor.calculate_best_node(doc)
        if top_node is not None:
            top_node = self.extractor.post_cleanup(top_node)

            text, article_html = output_formatter.get_formatted(
                top_node)

        self.is_parsed = True
        return text



    def get_parse_candidate(self):
        """A parse candidate is a wrapper object holding a link hash of this
        article and a final_url of the article
        """
        if self.html:
            return RawHelper.get_parsing_candidate(self.url, self.html)
        return URLHelper.get_parsing_candidate(self.url)

    def set_text(self, text):
        text = text[:self.config.MAX_TEXT]
        if text:
            self.text = text

    def set_html(self, html):
        """Encode HTML before setting it
        """
        if html:
            if isinstance(html, bytes):
                html = self.config.get_parser().get_unicode_html(html)
            self.html = html
            self.download_state = ArticleDownloadState.SUCCESS

    def set_article_html(self, article_html):
        """Sets the HTML of just the article's `top_node`
        """
        if article_html:
            self.article_html = article_html


    def throw_if_not_downloaded_verbose(self):
        """Parse ArticleDownloadState -> log readable status
        -> maybe throw ArticleException
        """
        if self.download_state == ArticleDownloadState.NOT_STARTED:
            print('You must `download()` an article first!')
            raise ArticleException()
        elif self.download_state == ArticleDownloadState.FAILED_RESPONSE:
            print('Article `download()` failed with %s on URL %s' %
                  (self.download_exception_msg, self.url))
            raise ArticleException()

    def throw_if_not_parsed_verbose(self):
        """Parse `is_parsed` status -> log readable status
        -> maybe throw ArticleException
        """
        if not self.is_parsed:
            print('You must `parse()` an article first!')
            raise ArticleException()
