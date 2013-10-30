import random

from models import Content, SubContent, Rating
from google.appengine.ext import ndb
from google.appengine.api import memcache

def query_content(ANNOTATION_NAME):
    query = Content.query(ancestor=ndb.Key('Content', ANNOTATION_NAME))
    return (query, query.count())

class ContentSampler():
    def __init__(self, ancestor, unrated=False):
        self.ancestor = ancestor
        self.unrated = unrated
        
    def __call__(self, user=None):
        (query, count) = query_content(self.ancestor)
        choices = range(count)
        while count > 0 and len(choices):
            choice = random.choice(choices)
            content = query.fetch(offset=choice, limit=1)[0]
            filters = Rating.content == content.key
            if user:
                filters = ndb.AND(Rating.user == user, filters)
                
            if self.unrated and \
                Rating.query(filters, \
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
        
    def __call__(self, user=None):
        query = Content.query(ancestor=ndb.Key('Content', self.ancestor))
        count = query.count()
        invalid_choices = memcache.get("invalid_content:" + user.email()) or []
        choices = filter(lambda choice: choice not in invalid_choices, range(count))
        while count > 0 and len(choices):
            choice = random.choice(choices)
            content = query.fetch(offset=choice, limit=1)[0]

            if self.unrated or self.sample_subcontent:
                subquery = SubContent.query(ancestor=content.key)
                subcontent_keys = subquery.fetch(keys_only=True)

            if self.unrated:
                if len(subcontent_keys) == 0:
                    filters = Rating.content == content.key
                else:
                    filters = Rating.content.IN(subcontent_keys)
                if user:
                    filters = ndb.AND(Rating.user == user, filters)
                ratings = Rating.query(filters, \
                              ancestor=ndb.Key('Rating', self.ancestor)).count()

                invalid  = self.sample_subcontent and ratings > 0
                invalid |= len(subcontent_keys) == 0 and ratings == 1
                invalid |= len(subcontent_keys) > 0 and ratings == len(subcontent_keys)
                if invalid:
                    choices.remove(choice)
                    invalid_choices.append(choice)
                    memcache.set("invalid_content:" + user.email(), invalid_choices)
                    continue
            
            if len(subcontent_keys) and self.sample_subcontent:
                content = random.choice(subcontent_keys).get()

            return content
        else:
            return None
