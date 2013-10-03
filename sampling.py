import random

from models import Content, SubContent, Rating
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

class SubContentSampler(ContentSampler):
    def __init__(self, ancestor, unrated=False, sample_subcontent=True):
        self.ancestor = ancestor
        self.unrated = unrated
        self.sample_subcontent = sample_subcontent
        
    def __call__(self):
        query = Content.query(ancestor=ndb.Key('Content', self.ancestor))
        count = query.count()
        choices = range(count)
        while count > 0 and len(choices):
            choice = random.choice(choices)
            content = query.fetch(offset=choice, limit=1)[0]

            if self.unrated or self.sample_subcontent:
                subquery = SubContent.query(ancestor=content.key)
                subcontent_keys = subquery.fetch(keys_only=True)

            if self.unrated:
                if len(subcontent_keys) == 0:
                    ratings = Rating.query(Rating.content == content.key, \
                                  ancestor=ndb.Key('Rating', self.ancestor)).count()
                else:
                    ratings = Rating.query(Rating.content.IN(subcontent_keys), \
                                  ancestor=ndb.Key('Rating', self.ancestor)).count()

                print len(subcontent_keys), ratings

                invalid  = self.sample_subcontent and ratings > 0
                invalid |= len(subcontent_keys) == 0 and ratings == 1
                invalid |= len(subcontent_keys) > 0 and ratings == len(subcontent_keys)
                if invalid:
                    choices.remove(choice)
                    continue

            if len(subcontent_keys) and self.sample_subcontent:
                content = random.choice(subcontent_keys).get()

            return content
        else:
            return None
