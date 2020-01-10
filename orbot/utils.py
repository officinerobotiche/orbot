# -*- coding: UTF-8 -*-
# This file is part of the orbot package (https://github.com/officinerobotiche/orbot or http://www.officinerobotiche.it).
# Copyright (C) 2020, Raffaello Bonghi <raffaello@rnext.it>
# All rights reserved
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
# 3. Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived
#    from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND
# CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING,
# BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS;
# OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
# WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE
# OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE,
# EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import logging
import csv
from os import path
from functools import wraps
from telegram.ext import ConversationHandler
# Offset flags
OFFSET = 127462 - ord('A')


logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


def check_key_id(message):
    def checkKeyID(func):
        @wraps(func)
        def wrapped(self, update, context):
            query = update.callback_query
            data = query.data.split()
            # Extract keyID and check
            keyID = data[1]
            if keyID not in context.user_data:
                query.edit_message_text(text=message, parse_mode='HTML')
                return ConversationHandler.END
            else:
                return func(self, update, context)
        return wrapped
    return checkKeyID

def filter_channel(func):
    @wraps(func)
    def wrapped(self, update, context):
        if update.effective_chat.type != 'channel':
            return func(self, update, context)
        return
    return wrapped

def build_menu(buttons, n_cols, header_buttons=None, footer_buttons=None):
    menu = [buttons[i:i + n_cols] for i in range(0, len(buttons), n_cols)]
    if header_buttons:
        menu.insert(0, [header_buttons])
    if footer_buttons:
        menu.append([footer_buttons])
    return menu


def isAdmin(update, context, user, chat_id=None):
    if chat_id is None:
        chat_id = update.effective_chat.id
    for member in context.bot.getChatAdministrators(chat_id):
        if member.user.username == user:
            return True
    return False


def hasNumbers(inputString):
    return any(char.isdigit() for char in inputString)


def flag(code):
    code = code.upper()
    return chr(ord(code[0]) + OFFSET) + chr(ord(code[1]) + OFFSET)


def saveFile(csv_file, dict_data):
    csv_columns = []
    if dict_data:
        csv_columns = list(dict_data[0].keys())
    else:
        return
    try:
        with open(csv_file, 'w') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=csv_columns)
            writer.writeheader()
            for data in dict_data:
                writer.writerow(data)
    except IOError:
        print("I/O error")


def LoadCSV(csv_file):
    dict_data = []
    if path.exists(csv_file):
        with open(csv_file) as csv_file:
            csv_reader = csv.reader(csv_file, delimiter=',')
            line_count = 0
            csv_columns = []
            for row in csv_reader:
                if line_count == 0:
                    csv_columns = row
                    line_count += 1
                else:
                    dict_data += [{k: int(v) if v.lstrip('-+').isdigit() else v for k, v in zip(csv_columns, row)}]
                    line_count += 1
    return dict_data