#!/usr/bin/env python

import os

from collections import defaultdict

import jinja2
import webapp2
import yaml

from google.appengine.ext import ndb
from google.appengine.api import users, memcache, mail

JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)),
    extensions=['jinja2.ext.autoescape'])

# We set a parent key on to ensure that they are all in the same
# entity group. Queries across the single entity group will be consistent.
# However, the write rate should be limited to ~1/second.

from models import Content, SubContent, Rating, Agreement, UserDetails
from sampling import SubContentSampler

class UserRequestHandler(webapp2.RequestHandler):
    def get_current_user(self,
                         redirect=False,
                         admin=False,
                         redirect_url=None):

        user = users.get_current_user()
        user_details = {}
        if user:
            user_details = {
                "user": user.nickname(),
                "is_admin": users.is_current_user_admin(),
                "logout_url": users.create_logout_url(self.request.uri),
                "request": self.request,
            }

        if redirect and (not user or (admin and not user_details['is_admin'])):
            if not redirect_url: 
                redirect_url = users.create_login_url(self.request.uri)
            self.redirect(redirect_url)
            user, user_details = None, {}

        return user, user_details

class TemplateHandler(UserRequestHandler):    
    def template_response(self, template, template_values={}, force_login=True):
        user, user_values = self.get_current_user(redirect=force_login)
        if not user: return
            
        template_values.update(user_values)
        try:
            template = JINJA_ENVIRONMENT.get_template(template)
        except jinja2.exceptions.TemplateNotFound:
            self.abort(404)
        self.response.write(template.render(template_values))
        
    def get(self, template):
        self.template_response(template + '.html')


class AnnotateHandler(TemplateHandler):
    def check_agreements(self):
        user, user_values = self.get_current_user(redirect=True)
        if not user: return False
            
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
        
    def get_statistics(self, user):
        annotation_streak = memcache.get("annotation_streak:" + user.user_id())
        if not annotation_streak: annotation_streak = 0
        if annotation_streak == 0 or annotation_streak >= ANNOTATION_BREAK_AFTER:
            memcache.set("annotation_streak:" + user.user_id(), 0, \
                         ANNOTATION_BREAK_TIMEOUT)
            if annotation_streak >= ANNOTATION_BREAK_AFTER:
                self.redirect("/break")
                return None
        memcache.incr("annotation_streak:" + user.user_id())        
        return annotation_streak

    def get(self):
        user, user_values = self.get_current_user(redirect=True)
        if not user: return

        if not self.check_agreements(): return
        annotation_streak = self.get_statistics(user)
        if annotation_streak == None: return
                
        values = {
            "NUMBER_OF_STARS": NUMBER_OF_STARS,
            "ANNOTATION_BREAK_AFTER": ANNOTATION_BREAK_AFTER,
            "annotation_streak": annotation_streak,
        }
        if USER_BASED_CONTENT_SAMPLING:
            values["content"] = CONTENT_SAMPLER(user)
        else:
            values["content"] = CONTENT_SAMPLER()
            
        if values["content"]:
            if RENDER_SUBCONTENT:
                query = SubContent.query(ancestor=values["content"].key)
                values["subcontents"] = query.fetch()
            self.template_response('annotate.html', values)
        else:
            self.redirect('/done')
        
    def post(self):
        user, user_values = self.get_current_user(redirect=True)
        if not user: return False
        
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
        self.template_response('leaderboard.html', values)

class AdminHandler(TemplateHandler):
    def get(self):
        if not self.get_current_user(True, True, '/'): return

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
        
        self.template_response('admin.html', template_values)

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
        if not self.get_current_user(True, True, '/'): return
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

        memcache.flush_all()
        self.redirect('/admin')

class MailHandler(webapp2.RequestHandler):
    def post(self):
        subject = "Feedback from %s app" % ANNOTATION_NAME 
        body = ""
        for argument in self.request.arguments():
            body += "%s: %s\n" % (argument, self.request.get(argument))

        mail.send_mail(FEEDBACK_MAILADDRESS, FEEDBACK_MAILADDRESS, subject, body)
        self.redirect('/done?mail_sent')

class FormHandler(TemplateHandler):
    def post(self):
        if not self.get_current_user(redirect=True): return

        details = UserDetails(user=user, 
                              age=int(self.request.get('AgeInYears')),
                              years_of_training=int(self.request.get('NYearsTraining')),
                              recruited_through_sona= \
                                self.request.get('recruitedThroughSona') == 'True',
                              parent=ndb.Key('UserDetails', ANNOTATION_NAME))
                                
        if self.request.get('SonaNumber'):
            details.sona_number = int(self.request.get('SonaNumber'))
            
        details.put()

        self.redirect('/annotate?agree=/form/')

    def get(self):
        self.template_response('form.html')

#

ANNOTATION_NAME = "Fleur-fMRI"
FEEDBACK_MAILADDRESS = "Fleur Bouwer <daan.odijk@gmail.com>"
NUMBER_OF_STARS = 10
CONTENT_SAMPLER = SubContentSampler(ANNOTATION_NAME, unrated=True, \
                                    sample_subcontent=True)
USER_BASED_CONTENT_SAMPLING = True
ANNOTATION_OBLIGATORY_AGREEMENTS = ['/introduction', '/form/', '/instruction', '/examples', '/start']
RENDER_SUBCONTENT = not CONTENT_SAMPLER.sample_subcontent
ANNOTATION_BREAK_AFTER = 5 # Number of annotations after which to force a break
ANNOTATION_BREAK_TIMEOUT = 300 # Number of seconds to remember a users streak

#

app = webapp2.WSGIApplication([
    ('/', AnnotateHandler),
    ('/annotate', AnnotateHandler),
    ('/leaderboard', LeaderboardHandler),
    ('/admin', AdminHandler),
    ('/mail', MailHandler),
    ('/form/', FormHandler),
    # Will match /anything if there is an anything.html 
    # (also /anything/ and /anything.html) and will show
    # the corresponding template anything.html
    (r'^/(.*?)(?:\.html)?/?$', TemplateHandler), 
], debug=True)
