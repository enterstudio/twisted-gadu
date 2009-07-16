#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright (c) 2009 Krzysztof 'kkszysiu' Klinikowski

from twisted.internet.protocol import ClientFactory
from twisted.internet.protocol import Protocol
from twisted.internet import reactor, defer
from twisted.python import log
import sys
import struct

from IncomingPackets import *
from OutgoingPackets import *
from HeaderPacket import GGHeader
from Helpers import *
from GGConstans import *
from Exceptions import *
from Contacts import *

log.startLogging(sys.stdout)

gg_uin = 4634020
gg_passwd = 'xxxxxx'
gg_status = GGStatuses.Avail
gg_desc = 'test'
#contacts_list = ContactsList()

class GGClient(Protocol):
    def __init__(self):
        self.uin = None
        self.password = None
        self.status = None
        self.desc = None
        self._header = True
        self.__local_ip = "127.0.0.1"
        self.__local_port = 1550
        self.__external_ip = "127.0.0.1"
        self.__external_port = 0
        self.__image_size = 255
        self.seed = None
        self.__contact_buffer = "" # bufor na importowane z serwera kontakty

    def sendPacket(self, msg):
        header = GGHeader()
	header.read(msg)
        print 'OUT header.type: ', header.type

        self.transport.write(msg)

    def connectionMade(self):
        Protocol.connectionMade(self)
        self._conn = self.factory._conn
        self.__contacts_list = self.factory._conn.contacts_list

    def dataReceived(self, data):
        print 'received data: ', data
        header = GGHeader()
	header.read(data)
        print 'header.type: ', header.type
        #logowanie
	if header.type == GGIncomingPackets.GGWelcome:
            print 'packet: GGWelcome'
            in_packet = GGWelcome()
            in_packet.read(data, header.length)
            self.seed = in_packet.seed
            d = defer.Deferred()
            d.callback(self)
            d.addCallback(self._conn.on_auth_got_seed, self.seed)
            d = None
        elif header.type == GGIncomingPackets.GGLoginOK:
            print 'packet: GGLoginOK'
            d = defer.Deferred()
            d.callback(self)
            d.addCallback(self._conn.on_login_ok)
            self._send_contacts_list()
            print 'wyslano liste kontaktow'
            self._ping()
        elif header.type == GGIncomingPackets.GGLoginFailed:
            print 'packet: GGLoginFailed'
            d = defer.Deferred()
            d.callback(self)
            d.addCallback(self._conn.on_login_failed)
        elif header.type == GGIncomingPackets.GGNeedEMail:
            print 'packet: GGNeedEMail'
            d = defer.Deferred()
            d.callback(self)
            d.addCallback(self._conn.on_need_email)
        elif header.type == GGIncomingPackets.GGDisconnecting:
            print 'packet: GGDisconnecting'
            in_packet = GGDisconnecting()
            in_packet.read(data, header.length)
            d = defer.Deferred()
            d.callback(self)
            d.addCallback(self._conn.on_disconnecting)
        elif header.type == GGIncomingPackets.GGNotifyReply60 or header.type == GGIncomingPackets.GGNotifyReply77:
            in_packet = GGNotifyReply(self.__contacts_list, header.type)
            in_packet.read(data, header.length)
            self.__contacts_list = in_packet.contacts
            d = defer.Deferred()
            d.callback(self)
            d.addCallback(self._conn.on_notify_reply, self.__contacts_list)
        #lista
        elif header.type == GGIncomingPackets.GGUserListReply:
            print 'packet: GGUserListReply'
            in_packet = GGUserListReply()
            in_packet.read(data, header.length)
            if in_packet.reqtype == GGUserListReplyTypes.GetMoreReply:
                self.__contact_buffer += in_packet.request
            if in_packet.reqtype == GGUserListReplyTypes.GetReply:
                self.__importing = False # zaimportowano cala liste
                self.__contact_buffer += in_packet.request #... bo lista moze przyjsc w kilku pakietach
                self.__make_contacts_list(self.__contact_buffer)
                self.__contact_buffer = "" # oprozniamy bufor
                d = defer.Deferred()
                d.callback(self)
                d.addCallback(self._conn.on_userlist_reply, self.__contacts_list)
            else:
                d = defer.Deferred()
                d.callback(self)
                d.addCallback(self._conn.on_userlist_exported_or_deleted, in_packet.reqtype, in_packet.request)
        #wiadomosci
        elif header.type == GGIncomingPackets.GGRecvMsg:
            in_packet = GGRecvMsg()
            in_packet.read(data, header.length)
            d = defer.Deferred()
            d.callback(self)
            d.addCallback(self._conn.on_msg_recv, in_packet.sender, in_packet.seq, in_packet.time, in_packet.msg_class, in_packet.message)
        elif header.type == GGIncomingPackets.GGSendMsgAck:
            in_packet = GGSendMsgAck()
            in_packet.read(data, header.length)
            d = defer.Deferred()
            d.callback(self)
            d.addCallback(self._conn.on_msg_ack, in_packet.status, in_packet.recipient, in_packet.seq)
        #statusy
        elif header.type == GGIncomingPackets.GGStatus:
            in_packet = GGStatus()
            in_packet.read(data, header.length)
            uin = in_packet.uin
            self.__contacts_list[uin].status = in_packet.status
            self.__contacts_list[uin].description = in_packet.description
            self.__contacts_list[uin].return_time = in_packet.return_time
            d = defer.Deferred()
            d.callback(self)
            d.addCallback(self._conn.on_status, self.__contacts_list[uin])
        elif header.type == GGIncomingPackets.GGStatus60:
            in_packet = GGStatus60()
            in_packet.read(data, header.length)
            uin = in_packet.uin
            if self.__contacts_list[uin] == None:
                self.__contacts_list.add_contact(Contact({"uin":in_packet.uin}))
            self.__contacts_list[uin].status = in_packet.status
            self.__contacts_list[uin].description = in_packet.description
            self.__contacts_list[uin].return_time = in_packet.return_time
            self.__contacts_list[uin].ip = in_packet.ip
            self.__contacts_list[uin].port = in_packet.port
            self.__contacts_list[uin].version = in_packet.version
            self.__contacts_list[uin].image_size = in_packet.image_size
            d = defer.Deferred()
            d.callback(self)
            d.addCallback(self._conn.on_status60, self.__contacts_list[uin])
        else:
            print 'packet: unknown: type %s, length %s' % (header.type, header.length)

    def _send_contacts_list(self):
        """
        Wysyla do serwera nasza liste kontaktow w celu otrzymania statusow.
        Powinno byc uzyte zaraz po zalogowaniu sie do serwera.
        UWAGA: To nie jest eksport listy kontaktow do serwera!
        """
        assert self.__contacts_list  == None or type(self.__contacts_list) == ContactsList
        print 'czas wyslac nasza liste kontaktow :D'
        if self.__contacts_list == None or len(self.__contacts_list) == 0:
            print 'yupp. wysylamy pusta liste kontaktow'
            out_packet = GGListEmpty()
            self.sendPacket(out_packet.get())
            return

        uin_type_list = [] # [(uin, type), (uin, type), ...]
        for contact in self.__contacts_list.data: #TODO: brrrrrrr, nie .data!!!!
            uin_type_list.append((contact.uin, contact.user_type))
        sub_lists = Helpers.split_list(uin_type_list, 400)

        for l in sub_lists[:-1]: #zostawiamy ostatnia podliste
            out_packet = GGNotifyFirst(l)
            self.sendPacket(out_packet.get())
        # zostala juz ostatnia lista do wyslania
        out_packet = GGNotifyLast(sub_lists[-1])
        self.sendPacket(out_packet.get())

    def _ping(self):
        """
        Metoda wysyla pakiet GGPing do serwera
        """
        out_packet = GGPing()
        self.sendPacket(out_packet.get())
        print "[PING]"
        reactor.callLater(96, self._ping)

    def __make_contacts_list(self, request):
            contacts = request.split("\n")
            if self.__contacts_list == None:
                    self.__contacts_list = ContactsList()
            for contact in contacts:
                    #TODO: needs to be fixed: groups
                    if contact != '' and contact != "\n" and (contact.find("GG70ExportString,;") >= 0) != True and contact != "GG70ExportString,;\r":
                            newcontact = Contact({'request_string':contact})
                            self.add_contact(newcontact)
        
    """Methods that can be used by user"""
    def login(self, seed, uin, password, status, desc):
        self.uin = uin
        self.password = password
        self.status = status
        self.desc = desc
	out_packet = GGLogin(self.uin, self.password, self.status, seed, self.desc, self.__local_ip, \
                            self.__local_port, self.__external_ip, self.__external_port, self.__image_size)
        self.sendPacket(out_packet.get())

    def change_status(self, status, description = ""):
            """
            Metoda powoduje zmiane statusu i opisu. Jako parametry przyjmuje nowy status i nowy opis (domyslnie - opis pusty).
            """
            assert type(status) == types.IntType and status in GGStatuses
            assert type(description) == types.StringType and len(description) <= 70

            out_packet  = GGNewStatus(status, description)
            self.sendPacket(out_packet.get())
            self.status = status
            self.desc = description

    def add_contact(self, contact, user_type = 0x3, notify = True):
            """
            Dodajemy kontakt 'contact' do listy kontaktow. Jesli jestesmy polaczeni z serwerem i notify == True to dodatkowo
            powiadamiamy o tym fakcie serwer. Od tego momentu serwer bedzie nas informowal o statusie tego kontaktu.
            """
            assert type(contact) == Contact
            self.__contacts_list.add_contact(contact)
            out_packet = GGAddNotify(contact.uin, user_type)
            self.sendPacket(out_packet.get())

    def remove_contact(self, uin, notify = True):
            """
            Usuwamy z listy kontaktow kontakt o numerze 'uin'. Jesli jestesmy polaczeni z serwerem i notify == True to dodatkowo
            powiadamiamy o tym fakcie serwer. Od tego momentu serwer nie bedzie nas juz informowal o statusie tego kontaktu.
            """
            self.__contacts_list.remove_contact(uin)
            out_packet = GGRemoveNotify(uin)
            self.sendPacket(out_packet.get())

    def change_user_type(self, uin, user_type):
            """
            Zmieniamy typ uzytkownika. user_type jest mapa wartosci z GGUserTypes.
            Np. zeby zablokowac uzytkownka piszemy:
                    change_user_type(12454354, GGUserTypes.Blocked)
            """
            out_packet = GGRemoveNotify(uin, user_type)
            self.sendPacket(out_packet.get())

    def change_description(self, description):
            """
            Metoda powoduje zmiane opisu. Jako parametr przyjmuje nowy opis.
            """
            assert type(description) == types.StringType and len(description) <= 70

            if self.status != GGStatuses.AvailDescr and self.status != GGStatuses.BusyDescr and self.status != GGStatuses.InvisibleDescr:
                    raise GGException("Can't change description - current status has'n description") 

            self.change_status(self.status, description)

    def send_msg(self, rcpt, msg, seq = 0, msg_class = GGMsgTypes.Msg, richtext = False):
            """
            Metoda sluzy do wysylania wiadomosci w siecie gadu-gadu. Parametry:
             * rcpt - numer gadu-gadu odbiorcy wiadomosci
             * msg - wiadomosc do dostarczenia
             * seq - numer sekwencyjny wiadomosci, sluzy do potwierdzen dostarczenia wiadomosci. Domyslnie wartosc 0
             * msg_class - klasa wiadomosci (typ GGMsgTypes). Domyslnie wiadomosc pojawia sie w nowym oknie
             * richtext - okresla czy wiadomosc bedzie interpretowana jako zwykly tekst czy jako tekst formatowany.
               Domyslnie nieformatowany
            """
            assert type(rcpt) == types.IntType
            assert type(msg) == types.StringType and ((not richtext and len(msg) < 2000) or (richtext))  #TODO: w dalszych iteracjach: obsluga richtextmsg
            assert type(seq) == types.IntType
            assert msg_class in GGMsgTypes

            if richtext:
                    message = Helpers.pygglib_rtf_to_gg_rtf(msg)
            else:
                    message = msg

            out_packet = GGSendMsg(rcpt, message, seq, msg_class)
            self.sendPacket(out_packet.get())

    def pubdir_request(self, request, reqtype = GGPubDirTypes.Search):
            """
            Metoda obslugujaca katalog publiczny. Wysyla zapytanie do serwera. Parametry:
             * request - zapytanie dla serwera
             * reqtype - typ zapytania
            """
            assert type(request) == types.StringType or type(request) == types.DictType
            assert reqtype in GGPubDirTypes

            out_packet = GGPubDir50Request(request, reqtype)
            self.sendPacket(out_packet.get())

    def export_contacts_list(self, filename = None):
            """
            Eksportuje liste kontaktow do serwera lub do pliku, w przypadku podania nazwy jako parametr filename
            """
            if self.__contacts_list != None:
                    if filename == None:
                            sub_lists = Helpers.split_list(self.__contacts_list.export_request_string(), 2038)
                            out_packet = GGUserListRequest(GGUserListTypes.Put, sub_lists[0])
                            self.sendPacket(out_packet.get())
                            if len(sub_lists) > 1:
                                    for l in sub_lists[1:len(sub_lists)]:
                                            out_packet = GGUserListRequest(GGUserListTypes.PutMore, l)
                                            self.sendPacket(out_packet.get())
                    else:
                            assert type(filename) == types.StringType
                            request = self.__contacts_list.export_request_string()
                            file = open(filename, "w")
                            file.write(request)
                            file.close()

    def delete_contacts_from_server(self):
            """
            Usuwa liste kontaktow z serwera Gadu-Gadu
            """
            out_packet = GGUserListRequest(GGUserListTypes.Put, "")
            self.sendPacket(out_packet.get())

    def import_contacts_list(self, filename = None):
            """
            Wysyla zadanie importu listy z serwera lub pliku, gdy podamy jego nazwe w parametrze filename.
            Zaimportowana lista zapisywana jest w self.__contacts_list
            """

            if filename == None:
                    out_packet = GGUserListRequest(GGUserListTypes.Get, "")
                    self.sendPacket(out_packet.get())
            else:
                    assert type(filename) == types.StringType
                    file = open(filename, "r")
                    request = file.read()
                    file.close()
                    self.__make_contacts_list(request)

    def get_actual_status(self):
        return self.status

    def get_actual_status_desc(self):
        return self.desc

class GGClientFactory(ClientFactory):
    protocol = GGClient
    def __init__(self, conn):
        self._conn = conn

    def startedConnecting(self, connector):
	print 'connection started'

    def clientConnectionFailed(self, connector, reason):
        print 'connection failed:', reason.getErrorMessage()
        reactor.stop()

    def clientConnectionLost(self, connector, reason):
        print 'connection lost:', reason.getErrorMessage()
        reactor.stop()

    def buildProtocol(self, addr):
      p = self.protocol()
      p.factory = self
      p.factory.instance = p
      return p

