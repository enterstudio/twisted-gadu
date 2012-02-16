#!/usr/bin/python

import os
import sys
import logging

from twisted.python import log

from twistedgadu.pygadu.twisted_protocol import GaduClient
from twistedgadu.pygadu.models import GaduProfile, GaduContact, GaduContactGroup

from twistedgadu.gaduapi import *
from twisted.web.client import getPage


from twisted.internet import reactor, protocol

logger = logging.getLogger('Gadu.Connection')
observer = log.PythonLoggingObserver(loggerName='Gadu.Connection')
observer.start()

#SSL
ssl_support = False

try:
    from OpenSSL import crypto, SSL
    from twisted.internet import ssl
    ssl_support = True
except ImportError:
    ssl_support = False
try:
    if ssl and ssl.supported:
        ssl_support = True
except NameError:
    ssl_support = False


if ssl_support == False:
    logger.info('SSL unavailable. Falling back to normal non-SSL connection.')
else:
    logger.info('Using SSL-like connection.')


class GaduClientFactory(protocol.ClientFactory):
    def __init__(self, config):
        self.config = config

    def buildProtocol(self, addr):
        # connect using current selected profile
        return GaduClient(self.config)

    def startedConnecting(self, connector):
        logger.info('Started to connect.')

    def clientConnectionLost(self, connector, reason):
        logger.info('Lost connection.  Reason: %s' % (reason))

        if reactor.running:
            reactor.stop()

    def clientConnectionFailed(self, connector, reason):
        logger.info('Connection failed. Reason: %s' % (reason))

        if reactor.running:
            reactor.stop()


class GaduConnection():

    def __init__(self, uin, password):

        try:
            self.profile = GaduProfile(uin = int(uin))
            self.profile.uin = int(uin)
            self.profile.password = str(password)
            self.profile.status = 0x014
            self.profile.onLoginSuccess = self.on_loginSuccess
            self.profile.onLoginFailure = self.on_loginFailed
            self.profile.onContactStatusChange = self.on_updateContact
            self.profile.onMessageReceived = self.on_messageReceived
            self.profile.onTypingNotification = self.onTypingNotification
            self.profile.onXmlAction = self.onXmlAction
            self.profile.onXmlEvent = self.onXmlEvent
            self.profile.onUserData = self.onUserData

            self.factory = GaduClientFactory(self.profile)

            self.param_use_ssl = True # use SSL

            logger.info("Connection to the account %s created" % uin)
        except Exception, e:
            import traceback
            logger.exception("Failed to create Connection")
            raise

    def Connect(self):
        #Dla self.makeConnection(ip/host servera, port)
        self.getServerAdress(self.profile.uin)

    def Disconnect(self):
        self.profile.disconnect()

        logger.info("Disconnecting")

    def getServerAdress(self, uin):
        logger.info("Fetching GG server adress.")
        url = 'http://appmsg.gadu-gadu.pl/appsvc/appmsg_ver10.asp?fmnumber=%s&lastmsg=0&version=10.1.1.11119' % (str(uin))
        d = getPage(url, timeout=10)
        d.addCallback(self.on_server_adress_fetched, uin)
        d.addErrback(self.on_server_adress_fetched_failed, uin)

    def makeConnection(self, ip, port):
        logger.info("%s %s %s" % (ip, port, self.param_use_ssl))
        if ssl_support and self.param_use_ssl:
            self.ssl = ssl.CertificateOptions(method=SSL.SSLv3_METHOD)
            reactor.connectSSL(ip, port, self.factory, self.ssl)
        else:
            reactor.connectTCP(ip, port, self.factory)

    def on_server_adress_fetched(self, result, uin):
        try:
            result = result.replace('\n', '')
            a = result.split(' ')
            if a[0] == '0' and a[-1:][0] != 'notoperating':
                addr = a[-1:][0]
                logger.info("GG server adress fetched, IP: %s" % (addr))
                if ssl_support and self.param_use_ssl:
                    port = 443
                    self.makeConnection(addr, port)
                else:
                    port = 8074
                    self.makeConnection(addr, port)
            else:
                raise Exception()
        except:
            logger.debug("Cannot get GG server IP adress. Trying again...")
            self.getServerAdress(uin)

    def on_server_adress_fetched_failed(self, error, uin):
        logger.error("Failed to get page with server IP adress.")

        self.factory.disconnect()

    def on_loginSuccess(self):
        logger.info("Connected")

    def on_loginFailed(self, response):
        logger.info("Login failed: ", response)

        reactor.stop()

    def on_updateContact(self, contact):
        logger.info("Method on_updateContact called, status changed for UIN: %s, id: %s, status: %s, description: %s" % (contact.uin, handle.id, contact.status, contact.get_desc()))

    def on_messageReceived(self, msg):
        if hasattr(msg.content.attrs, 'conference') and msg.content.attrs.conference != None:
            recipients = msg.content.attrs.conference.recipients
            recipients = map(str, recipients)
            recipients.append(str(msg.sender))
            recipients = sorted(recipients)
            conf_name = ', '.join(map(str, recipients))

            logger.info("Msg from %r %d %d [%r] [%r]" % (msg.sender, msg.content.offset_plain, msg.content.offset_attrs, msg.content.plain_message, msg.content.html_message))

            self._recv_id += 1

        else:
            if int(msg.content.klass) == 9:
                timestamp = int(msg.time)
            else:
                timestamp = int(time.time())

            logger.info("Msg from %r %d %d [%r] [%r]" % (msg.sender, msg.content.offset_plain, msg.content.offset_attrs, msg.content.plain_message, msg.content.html_message))

            self._recv_id += 1

    def onTypingNotification(self, data):
        logger.info("TypingNotification uin=%d, type=%d" % (data.uin, data.type))

    def onXmlAction(self, xml):
        logger.info("XmlAction: %s" % xml.data)

        #event occurs when user from our list change avatar
        #<events>
        #    <event id="12989655759719404037">
        #        <type>28</type>
        #        <sender>4634020</sender>
        #        <time>1270577383</time>
        #        <body></body>
        #        <bodyXML>
        #            <smallAvatar>http://avatars.gadu-gadu.pl/small/4634020?ts=1270577383</smallAvatar>
        #        </bodyXML>
        #    </event>
        #</events>
        try:
            tree = ET.fromstring(xml.data)
            core = tree.find("event")
            type = core.find("type").text
            if type == '28':
                sender = core.find("sender").text
                url = core.find("bodyXML/smallAvatar").text
                logger.info("XMLAction: Avatar Update")
                self.getAvatar(sender, url)
        except:
            pass

    def onXmlEvent(self, xml):
        logger.info("XmlEvent: %s" % xml,data)

    def onUserData(self, data):
        logger.info("UserData: %s" % str(data))
        #for user in data.users:
        #    print user.uin
        #    for attr in user.attr:
        #        print "%s - %s" % (attr.name, attr.value)


if __name__ == '__main__':
    conn = GaduConnection(4634020, 'xxxxxx')
    conn.Connect()

    try:
        reactor.run()
    except KeyboardInterrupt:
        if reactor.running:
            reactor.stop()