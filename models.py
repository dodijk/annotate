from google.appengine.ext import ndb

class Content(ndb.Model):
    """Models an individual content entry with author, content, and date."""
    author = ndb.UserProperty()
    content = ndb.StringProperty(indexed=False)
    date = ndb.DateTimeProperty(auto_now_add=True)

class SubContent(Content):
    """Models a subcontent entry, based on Content."""
    
class Rating(ndb.Model):
    """Models rating for content entries with user, Content, date and rating."""
    user = ndb.UserProperty()
    content = ndb.KeyProperty()
    date = ndb.DateTimeProperty(auto_now_add=True)
    rating = ndb.IntegerProperty()
    
class Agreement(ndb.Model):
    """Models an agreement of a user, url, and date."""
    user = ndb.UserProperty()
    url = ndb.StringProperty()
    date = ndb.DateTimeProperty(auto_now_add=True)

class UserDetails(ndb.Model):
    """Models details for an individual user."""
    user = ndb.UserProperty()
    created = ndb.DateTimeProperty(auto_now_add=True)
    age = ndb.IntegerProperty()
    years_of_training = ndb.IntegerProperty()
    recruited_through_sona = ndb.BooleanProperty()
    sona_number = ndb.IntegerProperty()

