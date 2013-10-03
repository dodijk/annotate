import random

from models import Content, Rating
from google.appengine.ext import ndb

def query_content(ANNOTATION_NAME):
    query = Content.query(ancestor=ndb.Key('Content', ANNOTATION_NAME))
    return (query, query.count())

class ContentSampler():
    def __init__(self, ancestor, unrated=False):
        self.ancestor = ancestor
        self.unrated = unrated
        
    def __call__(self):
        (query, count) = query_content(self.ancestor)
        choices = range(count)
        while count > 0 and len(choices):
            choice = random.choice(choices)
            content = query.fetch(offset=choice, limit=1)[0]
            if self.unrated and \
                Rating.query(Rating.content == content.key, \
                             ancestor=ndb.Key('Rating', self.ancestor)).count():
                choices.remove(choice)
            else:
                return content
        else:
            return None
