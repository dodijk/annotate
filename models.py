from google.appengine.ext import ndb

class Content(ndb.Model):
    """Models an individual content entry with author, content, and date."""
    author = ndb.UserProperty()
    content = ndb.StringProperty(indexed=False)
    date = ndb.DateTimeProperty(auto_now_add=True)
    
class Rating(ndb.Model):
    """Models rating for content entries with user, Content, date and rating."""
    user = ndb.UserProperty()
    content = ndb.KeyProperty(kind=Content)
    date = ndb.DateTimeProperty(auto_now_add=True)
    rating = ndb.IntegerProperty()
    
class Agreement(ndb.Model):
    """Models an agreement of a user, url, and date."""
    user = ndb.UserProperty()
    url = ndb.StringProperty()
    date = ndb.DateTimeProperty(auto_now_add=True)
