#!/usr/bin/env python

import os

from collections import defaultdict

import jinja2
import webapp2

from google.appengine.ext import ndb
from google.appengine.api import users, memcache

JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)),
    extensions=['jinja2.ext.autoescape'])

# We set a parent key on to ensure that they are all in the same
# entity group. Queries across the single entity group will be consistent.
# However, the write rate should be limited to ~1/second.

from models import Content, Rating, Agreement
from sampling import ContentSampler

class TemplateHandler(webapp2.RequestHandler):
    def is_logged_in(self):
        user = users.get_current_user()
        if not user: return user, {}
    
        return user, {
            "user": user.nickname(),
            "is_admin": users.is_current_user_admin(),
            "logout_url": users.create_logout_url(self.request.uri),
        }
    
    def logged_in_template_response(self, template, template_values={}):
        user, user_values = self.is_logged_in()
        if not user:
            self.redirect(users.create_login_url(self.request.uri))
        else:
            template_values.update(user_values)
            try:
                template = JINJA_ENVIRONMENT.get_template(template)
            except:
                self.abort(404)
            self.response.write(template.render(template_values))

    def current_user_is_admin_or_redirect(self):
        user = users.get_current_user()
        if not user or not users.is_current_user_admin():
            self.redirect('/')
        return user
        
    def get(self, template):
        self.logged_in_template_response(template + '.html')


class AnnotateHandler(TemplateHandler):
    def check_agreements(self):
        user, user_values = self.is_logged_in()
        if not user:
            self.redirect(users.create_login_url(self.request.uri))
            return False
            
        agreed = memcache.get("agreed:" + user.user_id())
        if agreed and agreed >= set(ANNOTATION_OBLIGATORY_AGREEMENTS):
            return True

        agree = self.request.get('agree', None)
        if agree:
            Agreement(user=user, url=agree,
                      parent=ndb.Key('Agreement', ANNOTATION_NAME)).put()
        for agreement in ANNOTATION_OBLIGATORY_AGREEMENTS:
            if not Agreement.query(Agreement.user==user and \
                                   Agreement.url == agreement, 
                        ancestor=ndb.Key('Agreement', ANNOTATION_NAME)).count():
                self.redirect(agreement)
                return False
        
        memcache.add("agreed:" + user.user_id(), set(ANNOTATION_OBLIGATORY_AGREEMENTS))
        return True

    def get(self):
        if not self.check_agreements(): return
                  
        values = {
            "NUMBER_OF_STARS": NUMBER_OF_STARS,
            "content": CONTENT_SAMPLER(),
        }
        if values["content"]:
            self.logged_in_template_response('annotate.html', values)
        else:
            self.redirect('/done')
        
    def post(self):
        user, user_values = self.is_logged_in()
        if not user:
            return self.redirect(users.create_login_url(self.request.uri))
        
        rating = Rating(user=user, 
                        rating=int(self.request.get('stars')),
                        content=ndb.Key(urlsafe=self.request.get('content_id')),
                        parent=ndb.Key('Rating', ANNOTATION_NAME))
        rating.put()
        
        self.redirect('/annotate')
        
class LeaderboardHandler(TemplateHandler):
    def get(self):
        query = Rating.query(ancestor=ndb.Key('Rating', ANNOTATION_NAME))
        
        counts = defaultdict(int)
        for rating in query.fetch():
            counts[rating.user] += 1

        values = {"counts": sorted(counts.iteritems(), key=lambda x: x[1], reverse=True)}
        self.logged_in_template_response('leaderboard.html', values)

class AdminHandler(TemplateHandler):
    def get(self):
        if not self.current_user_is_admin_or_redirect(): return
        query = Rating.query(ancestor=ndb.Key('Rating', ANNOTATION_NAME))
        counts = defaultdict(int)
        for rating in query.fetch():
            counts[rating.content.urlsafe()] += 1
        
        template_values = {
            "contents": Content.query(ancestor=ndb.Key('Content', ANNOTATION_NAME)) \
                                  .order(-Content.date).fetch(),
            "counts": counts,
        }
        
        self.logged_in_template_response('admin.html', template_values)
    
    def post(self):
        user = self.current_user_is_admin_or_redirect()
        if not user: return
        content = Content(author=user, 
                          content=self.request.get('content'),
                          parent=ndb.Key('Content', ANNOTATION_NAME))
        content.put()
        self.redirect('/admin')

#

ANNOTATION_NAME = "Fleur-fMRI"
NUMBER_OF_STARS = 5
CONTENT_SAMPLER = ContentSampler(ANNOTATION_NAME, unrated=True)
ANNOTATION_OBLIGATORY_AGREEMENTS = ['/instruction']

#

app = webapp2.WSGIApplication([
    ('/', AnnotateHandler),
    ('/annotate', AnnotateHandler),
    ('/leaderboard', LeaderboardHandler),
    ('/admin', AdminHandler),
    # Will match /anything if there is an anything.html 
    # (also /anything/ and /anything.html) and will show
    # the corresponding template anything.html
    (r'^/(.*?)(?:\.html)?/?$', TemplateHandler), 
], debug=True)
