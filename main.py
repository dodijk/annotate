#!/usr/bin/env python

import os

from collections import defaultdict

import jinja2
import webapp2
import yaml

from google.appengine.ext import ndb
from google.appengine.api import users, memcache

JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)),
    extensions=['jinja2.ext.autoescape'])

# We set a parent key on to ensure that they are all in the same
# entity group. Queries across the single entity group will be consistent.
# However, the write rate should be limited to ~1/second.

from models import Content, SubContent, Rating, Agreement
from sampling import SubContentSampler

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
            except jinja2.exceptions.TemplateNotFound:
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
        user, user_values = self.is_logged_in()
        if not user:
            return self.redirect(users.create_login_url(self.request.uri))

        if not self.check_agreements(): return
                  
        values = {
            "NUMBER_OF_STARS": NUMBER_OF_STARS,
        }
        if USER_BASED_CONTENT_SAMPLING:
            values["content"] = CONTENT_SAMPLER(user)
        else:
            values["content"] = CONTENT_SAMPLER()
            
        if values["content"]:
            if RENDER_SUBCONTENT:
                query = SubContent.query(ancestor=values["content"].key)
                values["subcontents"] = query.fetch()
            self.logged_in_template_response('annotate.html', values)
        else:
            self.redirect('/done')
        
    def post(self):
        user, user_values = self.is_logged_in()
        if not user:
            return self.redirect(users.create_login_url(self.request.uri))
        
        for rating, content_id in zip(self.request.POST.getall('stars'), \
                                      self.request.POST.getall('content_id')):
            rating = Rating(user=user, 
                            rating=int(rating),
                            content=ndb.Key(urlsafe=content_id),
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
        for rating in query.fetch(projection=['content']):
            counts[rating.content.urlsafe()] += 1

        subcontents = defaultdict(list)
        query = SubContent.query(ancestor=ndb.Key('Content', ANNOTATION_NAME))
        for subcontent in query.fetch():
            subcontents[subcontent.key.parent().urlsafe()] += subcontent,
        
        template_values = {
            "contents": Content.query(ancestor=ndb.Key('Content', ANNOTATION_NAME)) \
                                  .order(Content.date).fetch(),
            "counts": counts,
            "subcontents": subcontents,
        }
        
        self.logged_in_template_response('admin.html', template_values)

    def add_content(self, author, content, parent=None):
        if type(content) != str: content = str(content)
        if parent:
            content = SubContent(author=author, content=content,
                                 parent=ndb.Key(urlsafe=parent))
        else:
            content = Content(author=author, content=content,
                             parent=ndb.Key('Content', ANNOTATION_NAME))
        return content.put()
    
    def post(self):
        user = self.current_user_is_admin_or_redirect()
        if not user: return
        if self.request.get('isYAML') == 'on':
            data = yaml.load(self.request.get('content'))
            if not data: raise ValueError("No YAML data")
            if "content" not in data:
                raise ValueError("No content in YAML data")

            if "template" in data:
                data["template"] = \
                    JINJA_ENVIRONMENT.from_string(data['template'])
            if "subtemplate" in data:
                data["subtemplate"] = \
                    JINJA_ENVIRONMENT.from_string(data['subtemplate'])

            if type(data["content"]) == dict:
                for content, subcontents in data["content"].iteritems():
                    if "template" in data: content = data["template"].render(content)
                    key = self.add_content(user, content)
                    for subcontent in subcontents:
                        if "subtemplate" in data: 
                            subcontent = data["subtemplate"].render(subcontent)
                        self.add_content(user, subcontent, key.urlsafe())
            elif type(data["content"]) == list:
                for content in data["content"].iteritems():
                    if "template" in data: content = data["template"].render(content)                
                    self.add_content(user, content)
            else:
                raise ValueError("Unknown type of content")

        elif self.request.get('parent') != "":
            self.add_content(user, self.request.get('content'), \
                                   self.request.get('parent'))
        else:
            self.add_content(user, self.request.get('content'))
        self.redirect('/admin')

#

ANNOTATION_NAME = "Fleur-fMRI"
NUMBER_OF_STARS = 5
CONTENT_SAMPLER = SubContentSampler(ANNOTATION_NAME, unrated=True, \
                                    sample_subcontent=True)
USER_BASED_CONTENT_SAMPLING = True
ANNOTATION_OBLIGATORY_AGREEMENTS = ['/introduction', '/instruction', '/examples', '/start']
RENDER_SUBCONTENT = not CONTENT_SAMPLER.sample_subcontent

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
