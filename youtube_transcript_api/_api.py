import sys

# This can only be tested by using different python versions, therefore it is not covered by coverage.py
if sys.version_info.major == 2: # pragma: no cover
    reload(sys)
    sys.setdefaultencoding('utf-8')

from xml.etree import ElementTree

import re

import requests

from ._html_unescaping import unescape


class YouTubeTranscriptApi():
    class CouldNotRetrieveTranscript(Exception):
        """
        Raised if a transcript could not be retrieved.
        """

        ERROR_MESSAGE = (
            'Could not get the transcript for the video {video_url}! '
            'This usually happens if one of the following things is the case:\n'
            ' - subtitles have been disabled by the uploader\n'
            ' - none of the language codes you provided are valid\n'
            ' - none of the languages you provided are supported by the video\n'
            ' - the video is no longer available.\n\n'
            'If none of these things is the case, please create an issue at '
            'https://github.com/jdepoix/youtube-transcript-api/issues.'
            'Please add which version of youtube_transcript_api you are using and make sure that there '
            'are no open issues which already describe your problem!'
        )

        def __init__(self, video_id):
            super(YouTubeTranscriptApi.CouldNotRetrieveTranscript, self).__init__(
                self.ERROR_MESSAGE.format(video_url=_TranscriptFetcher.WATCH_URL.format(video_id=video_id))
            )
            self.video_id = video_id

    @classmethod
    def get_transcripts(cls, video_ids, languages=('en',), continue_after_error=False, proxies=None):
        """
        Retrieves the transcripts for a list of videos.

        :param video_ids: a list of youtube video ids
        :type video_ids: [str]
        :param languages: A list of language codes in a descending priority. For example, if this is set to ['de', 'en']
        it will first try to fetch the german transcript (de) and then fetch the english transcipt (en) if it fails to
        do so. As I can't provide a complete list of all working language codes with full certainty, you may have to
        play around with the language codes a bit, to find the one which is working for you!
        :type languages: [str]
        :param continue_after_error: if this is set the execution won't be stopped, if an error occurs while retrieving
        one of the video transcripts
        :type continue_after_error: bool
        :param proxies: a dictionary mapping of http and https proxies to be used for the network requests
        :type proxies: {'http': str, 'https': str} - http://docs.python-requests.org/en/master/user/advanced/#proxies
        :return: a tuple containing a dictionary mapping video ids onto their corresponding transcripts, and a list of
        video ids, which could not be retrieved
        :rtype: ({str: [{'text': str, 'start': float, 'end': float}]}, [str]}
        """
        data = {}
        unretrievable_videos = []

        for video_id in video_ids:
            try:
                data[video_id] = cls.get_transcript(video_id, languages, proxies)
            except Exception as exception:
                if not continue_after_error:
                    raise exception

                unretrievable_videos.append(video_id)

        return data, unretrievable_videos

    @classmethod
    def get_transcript(cls, video_id, languages=('en',), proxies=None):
        """
        Retrieves the transcript for a single video.

        :param video_id: the youtube video id
        :type video_id: str
        :param languages: A list of language codes in a descending priority. For example, if this is set to ['de', 'en']
        it will first try to fetch the german transcript (de) and then fetch the english transcript (en) if it fails to
        do so. As I can't provide a complete list of all working language codes with full certainty, you may have to
        play around with the language codes a bit, to find the one which is working for you!
        :type languages: [str]
        :param proxies: a dictionary mapping of http and https proxies to be used for the network requests
        :type proxies: {'http': str, 'https': str} - http://docs.python-requests.org/en/master/user/advanced/#proxies
        :return: a list of dictionaries containing the 'text', 'start' and 'duration' keys
        :rtype: [{'text': str, 'start': float, 'end': float}]
        """
        try:
            return _TranscriptParser(_TranscriptFetcher(video_id, languages, proxies).fetch()).parse()
        except Exception:
            raise YouTubeTranscriptApi.CouldNotRetrieveTranscript(video_id)


class _TranscriptFetcher():
    WATCH_URL = 'https://www.youtube.com/watch?v={video_id}'
    API_BASE_URL = 'https://www.youtube.com/api/'
    TIMEDTEXT_STRING = 'timedtext?v='
    NAME_REGEX = re.compile(r'&name=.*?(&)|&name=.*')

    def __init__(self, video_id, languages, proxies):
        self.video_id = video_id
        self.languages = languages
        self.proxies = proxies

    def fetch(self):
        if self.proxies:
            fetched_site = requests.get(self.WATCH_URL.format(video_id=self.video_id), proxies=self.proxies).text
        else:
            fetched_site = requests.get(self.WATCH_URL.format(video_id=self.video_id)).text
        timedtext_splits = [split[:split.find('"')]
                .replace('\\u0026', '&')
                .replace('\\', '') 
                for split in fetched_site.split(self.TIMEDTEXT_STRING)]
        matched_splits = []
        for language in self.languages:
            matched_splits = [split for split in timedtext_splits if '&lang={}'.format(language) in split]
            if matched_splits:
                break
        if matched_splits:
            timedtext_url = min(matched_splits, key=self._sort_splits)
            response = self._execute_api_request(timedtext_url)
            if response:
                return response

        return None

    def _sort_splits(self, matched_split):
        """Returns a value related to a given caption track url.

        This function is used to sort the matched splits by string 
        length because we want non-asr and non-dialect options returned first.
        With this in mind, it is remove the 'name' arugument from the url as 
        it could possibly make the values inaccurate to what we desire.

        matched_split: The caption track url we want to return a value for.        
        """
        return len(re.sub(self.NAME_REGEX, r'\1', matched_split))

    def _execute_api_request(self, timedtext_url):
        url = '{}{}{}'.format(self.API_BASE_URL, self.TIMEDTEXT_STRING, timedtext_url)
        if self.proxies:
            return requests.get(url, proxies=self.proxies).text
        else:
            return requests.get(url).text


class _TranscriptParser():
    HTML_TAG_REGEX = re.compile(r'<[^>]*>', re.IGNORECASE)

    def __init__(self, plain_data):
        self.plain_data = plain_data

    def parse(self):
        return [
            {
                'text': re.sub(self.HTML_TAG_REGEX, '', unescape(xml_element.text)),
                'start': float(xml_element.attrib['start']),
                'duration': float(xml_element.attrib['dur']),
            }
            for xml_element in ElementTree.fromstring(self.plain_data)
            if xml_element.text is not None
        ]
