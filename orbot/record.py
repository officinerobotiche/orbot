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


import re
from uuid import uuid1, uuid4
from collections import deque
import os
from telegram.ext import (Updater,
                          CommandHandler,
                          CallbackQueryHandler,
                          MessageHandler,
                          Filters,
                          CallbackContext,
                          ConversationHandler)
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Bot, TelegramError
import logging
from datetime import datetime, timedelta
import shutil
from urllib.parse import urlparse
from os.path import splitext, basename
# Menu 
from .utils import build_menu, check_key_id, isAdmin, filter_channel, restricted, rtype, zip_record

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

BETA = False
START = 'start'
STOP = 'stop'

class Autoreply:

    def __init__(self, updater, context, chat_id, type, text, func_timeout, data, time=60, interval=10, keyID=None):
        # Usually th e keyID is automatically generated.
        # Do not use a keyID in a job timer message
        if keyID is None:
            # Generate ID and seperate value from command
            keyID = str(uuid4())
            # Set the user data
            context.user_data[keyID] = {'chat_id': chat_id}
        # set total time
        self.time = time
        # Interval update message
        self.interval = interval
        # Make control buttons
        msg = self.ctrl_buttons(context, chat_id, keyID, type, text)
        # Initialize the context to share
        data_timer = {'timer': self.time,
                      'message': msg.message_id,
                      'chat_id': chat_id,
                      'keyID': keyID,
                      'text': text,
                      'func_timeout': func_timeout,
                      'data': data,
                      'type_cb': type}
        # add job in recording dictionary
        self.job = updater.job_queue.run_repeating(self.timer_autoreply, context=data_timer, interval=self.interval, first=self.interval)

    def stop(self):
        # Stop the autoreply timer
        self.job.enabled = False  # Temporarily disable this job
        self.job.schedule_removal()  # Remove this job completely

    def timer_autoreply(self, context: CallbackContext):
        # Get job data
        job = context.job
        data_timer = context.job.context
        # Extract all context parameter
        timer = data_timer['timer']
        message_id = data_timer['message']
        chat_id = data_timer['chat_id']
        keyID = data_timer['keyID']
        text = data_timer['text']
        type_cb = data_timer['type_cb']
        # Update control buttons and text
        self.ctrl_buttons(context, chat_id, keyID, type_cb, f"{text} _({timer}s left)_", message_id)
        # Decrease timer
        context.job.context['timer'] -= self.interval
        # If timer left remove timer and send a message
        if timer <= 0:
            job.schedule_removal()
            # Send the message
            func_timeout = data_timer['func_timeout']
            data = [type_cb, keyID, data_timer['data']]
            func_timeout(context, message_id, chat_id, data)

    def ctrl_buttons(self, context, chat_id, keyID, type_cb, message, edit_msg=None):
        yes = InlineKeyboardButton("✅", callback_data=f"{type_cb} {keyID} true")
        no = InlineKeyboardButton("❌", callback_data=f"{type_cb} {keyID} false")
        reply_markup = InlineKeyboardMarkup(build_menu([yes, no], 2))
        if edit_msg is not None:
            context.bot.edit_message_text(chat_id=chat_id,
                                          message_id=edit_msg,
                                          text=message,
                                          parse_mode='Markdown',
                                          reply_markup=reply_markup)
            return None
        else:
            return context.bot.send_message(chat_id=chat_id,
                                           text=message,
                                           parse_mode='Markdown',
                                           reply_markup=reply_markup)

IDLE, WAIT_START, WAIT_STOP, WRITING = range(4)
RECORDING = 'RECORDING'
MSG_TEXT_ORDER = ['date', 'user_id', 'firstname', 'msg_id', 'reply_id', 'forward_from', 'text']

def make_dict_message(update, text):
    # Message ID
    msg_id = update.message.message_id
    # date message
    date = update.message.date
    # User ID
    user_id = update.message.from_user.id
    # Username
    username = update.message.from_user.username
    # Name
    firstname = update.message.from_user.first_name
    # Reply id
    reply_id = update.message.reply_to_message.message_id if update.message.reply_to_message else ''
    # Reply id
    forward_from = update.message.forward_from.id if update.message.forward_from else ''
    # Make message
    msg = {'msg_id': msg_id,
            'date': date,
            'user_id': user_id,
            'firstname': firstname,
            'username': username,
            'text': text,
            'reply_id': reply_id,
            'forward_from': forward_from}
    return msg


class Record:

    def __init__(self, updater, settings, settings_file, channels):
        self.updater = updater
        self.settings_file = settings_file
        self.settings = settings
        self.channels = channels
        # Timeout autostop
        self.timeout = 10 * 60
        self.extension = "csv"
        self.size_record_chat = 10
        self.min_delta = 10
        self.d_start = 10 * 60
        self.separator = "\t"
        # Recording status
        self.recording = {}
        # Initialize folder records
        records = self.settings['config'].get('records', {})
        self.records_folder = records.get('folder', 'records')
        if not os.path.isdir(self.records_folder):
            os.mkdir(self.records_folder)
            logger.info(f"Directory {self.records_folder} created")
        # Job queue
        self.job = self.updater.job_queue
        # Get the dispatcher to register handlers
        dp = self.updater.dispatcher
        # Text recorder
        text_handler = MessageHandler(Filters.text, self.record)
        dp.add_handler(text_handler)
        photo_handler = MessageHandler(Filters.photo, self.record_photo)
        dp.add_handler(photo_handler)
        document_handler = MessageHandler(Filters.document, self.record_document)
        dp.add_handler(document_handler)
        # Query messages
        dp.add_handler(CommandHandler('records', self.records))
        dp.add_handler(CallbackQueryHandler(self.rec_folder, pattern='REC_DATA'))
        dp.add_handler(CallbackQueryHandler(self.rec_download, pattern='REC_DOWNLOAD'))
        dp.add_handler(CallbackQueryHandler(self.rec_cancel, pattern='REC_CN'))
        dp.add_handler(CallbackQueryHandler(self.start, pattern='REC_START'))
        dp.add_handler(CallbackQueryHandler(self.stop, pattern='REC_STOP'))
        dp.add_handler(CallbackQueryHandler(self.timer_stop_cb, pattern='REC_TIMER_STOP'))

    def close_all_records(self, bot):
        for chat_id in self.recording:
            if self.recording[chat_id]['status'] not in [IDLE]:
                # Set in idle mode and wait a new record
                self.idle(bot, chat_id)
                # Set in idle mode
                self.recording[chat_id]['status'] = IDLE
                # Send message
                text = f"🛑 Recording *stop*!"
                bot.send_message(chat_id=chat_id, text=text, parse_mode='Markdown')

    def get_folders(self, context, user_id, keyID):
        buttons = []
        # List all folders
        for folder in os.listdir(self.records_folder):
            chat_id = "-" + folder
            user_chat = context.bot.get_chat_member(chat_id, user_id)
            if user_chat.status not in ['left', 'kicked'] and len(os.listdir(f"{self.records_folder}/{folder}") ) != 0:
                chat = context.bot.getChat(chat_id)
                buttons += [InlineKeyboardButton(chat.title, callback_data=f"REC_DATA {keyID} {folder}")]
        # Build reply markup
        if buttons:
            message = 'List of records:'
            reply_markup = InlineKeyboardMarkup(build_menu(buttons, 1, footer_buttons=InlineKeyboardButton("Cancel", callback_data=f"REC_CN {keyID}")))
        else:
            message = 'No records'
            reply_markup = InlineKeyboardMarkup(buttons)
        return message, reply_markup

    def get_records_list(self, context, keyID, folder_chat):
        path = f"{self.records_folder}/{folder_chat}"
        buttons = []
        if os.path.isdir(path):
            list_dir = [x for x in os.listdir(path) if os.path.isdir(os.path.join(path, x))]
            context.user_data[keyID]['folder'] = sorted(list_dir)
            for idx, rec in enumerate(context.user_data[keyID]['folder']):
                chat_id = "-" + folder_chat
                if int(chat_id) in self.recording:
                    if self.recording[int(chat_id)]['status'] in [WRITING, WAIT_STOP]:
                        continue
                filename = str(datetime.fromtimestamp(int(rec)))
                buttons += [InlineKeyboardButton("📼 " + filename, callback_data=f"REC_DOWNLOAD {keyID} {idx}")]
            # Build reply markup
            chat_id = "-" + folder_chat
            chat = context.bot.getChat(chat_id)
        if buttons:
            message = f"📼 *Records* _from_ {chat.title}"
            reply_markup = InlineKeyboardMarkup(build_menu(buttons, 1, footer_buttons=InlineKeyboardButton("Cancel", callback_data=f"REC_CN {keyID}")))
        else:
            message = 'No records'
            reply_markup = InlineKeyboardMarkup(buttons)
        return message, reply_markup

    @rtype(['private', 'channel'])
    def records(self, update, context):
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        # Generate ID and seperate value from command
        keyID = str(uuid4())
        # Store value
        context.user_data[keyID] = {}
        # Check user type
        if update.message.chat.type == 'private':
            # List of all folders
            message, reply_markup = self.get_folders(context, user_id, keyID)
        else:
            # Attention chat in absolute value !!!!!!!!!!!!!
            folder_name = str(chat_id)[1:]
            context.user_data[keyID]['folder_name'] = folder_name
            message, reply_markup = self.get_records_list(context, keyID, folder_name)
        # Send message
        context.bot.send_message(chat_id=update.effective_user.id, text=message, parse_mode='Markdown', reply_markup=reply_markup)

    @check_key_id('Error message')
    def rec_folder(self, update, context):
        query = update.callback_query
        data = query.data.split()
        # Extract keyID, chat_id and title
        keyID = data[1]
        folder_chat = data[2]
        context.user_data[keyID]['folder_name'] = folder_chat
        # Make list of records
        message, reply_markup = self.get_records_list(context, keyID, folder_chat)
        query.edit_message_text(text=message, reply_markup=reply_markup, parse_mode='Markdown')

    @check_key_id('Error message')
    def rec_download(self, update, context):
        query = update.callback_query
        chat_id = query.message.chat.id
        data = query.data.split()
        # Extract keyID, chat_id and title
        keyID = data[1]
        folder_idx = data[2]
        folder_chat = context.user_data[keyID]['folder_name']
        folder_download = context.user_data[keyID]['folder'][int(folder_idx)]
        path_document = f"{self.records_folder}/{folder_chat}/{folder_download}"
        # Document info
        chat = context.bot.getChat("-" + folder_chat)
        #filename, _ = os.path.splitext(folder_download)
        filename = str(datetime.fromtimestamp(int(folder_download)))
        option = data[3] if len(data) == 4 else ""
        # Select extra option for admin
        if not self.channels.isRestricted(update, context) and not option:
            buttons = [InlineKeyboardButton("📼 Download", callback_data=f"REC_DOWNLOAD {keyID} {folder_idx} download"),
                       InlineKeyboardButton("🧹 Remove", callback_data=f"REC_DOWNLOAD {keyID} {folder_idx} delete")]
            reply_markup = InlineKeyboardMarkup(build_menu(buttons, 3, footer_buttons=InlineKeyboardButton("Cancel", callback_data=f"REC_CN {keyID}")))
            text = f"📼 {filename} _from_ {chat.title}"
            query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            if option == 'download':
                #query.edit_message_text(text=text, parse_mode='Markdown')
                context.bot.delete_message(chat_id=chat_id, message_id=query.message.message_id)
                # Record information
                self.send_record(context.bot, chat_id, folder_chat, folder_download)
            elif option == 'delete':
                # Remove file
                shutil.rmtree(path_document)
                # Write text information
                text = f"🧹 *Removed* 📼 {filename} _from_ {chat.title}"
                query.edit_message_text(text=text, parse_mode='Markdown')
            # remove key from user_data list
            del context.user_data[keyID]

    def send_record(self, bot, chat_id, folder_chat, folder_download):
        path_document = f"{self.records_folder}/{folder_chat}/{folder_download}"
        # Document info
        chat = bot.getChat("-" + folder_chat)
        filename = str(datetime.fromtimestamp(int(folder_download)))
        # Record information
        data_folder = os.listdir(path_document)
        if len(data_folder) > 1:
            logger.info(f"Make a zip and send records of {folder_download} in {folder_chat}")
            # path zip file
            document = f"{path_document}/{filename}.zip"
            # Zip folder
            zip_record(document, path_document)
        else:
            # Extract name document
            file_record = data_folder[0]
            # make final path
            document = f"{path_document}/{file_record}"
        # Sending file
        bot.send_document(chat_id=chat_id, document=open(document, 'rb'), caption=f"📼 _from_ {chat.title}", parse_mode='Markdown')
        # Remove zip file if exist
        if os.path.isfile(f"{path_document}/{filename}.zip"):
            os.remove(f"{path_document}/{filename}.zip")


    @check_key_id('Error message')
    def rec_cancel(self, update, context):
        query = update.callback_query
        data = query.data.split()
        # Extract keyID, chat_id and title
        keyID = data[1]
        # remove key from user_data list
        del context.user_data[keyID]
        # edit message
        query.edit_message_text(text="<b>Abort</b>", parse_mode='HTML')

    def job_timer_reset(self, chat_id):
        # Stop the timer
        self.job_timer_stop(chat_id)
        # Start timer
        self.job_timer_start(chat_id)

    def job_timer_start(self, chat_id):
        # add job in recording dictionary
        records = self.settings['config'].get('records', {})
        timeout = int(records.get('timeout', self.timeout))
        self.recording[chat_id]['job'] = self.job.run_once(self.timer_stop, timeout, context=chat_id)

    def job_timer_stop(self, chat_id):
        if 'job' in self.recording[chat_id]:
            job = self.recording[chat_id]['job']
            # Stop the timer
            job.enabled = False  # Temporarily disable this job
            job.schedule_removal()  # Remove this job completely

    def job_timer_delete(self, chat_id):
        if 'job' in self.recording[chat_id]:
            # Remove timer
            del self.recording[chat_id]['job']

    def record_filter(self, update, context):
        # Check is the message is not empty
        if update.message is None:
            logger.info("Empty message or edited")
            return True
        # Check if not a private chat
        if update.message.chat.type == 'private':
            logger.info("Private chat")
            return True
        chat_id = update.effective_chat.id
        if str(chat_id) not in self.settings['channels']:
            logger.info("Chat not authorized")
            return True
        # Enable only beta channels
        if BETA:
            if not self.settings['channels'][str(chat_id)].get('beta', False):
                return True
        # initialization recording chat
        records = self.settings['config'].get('records', {})
        if chat_id not in self.recording:
            size_record_chat = int(records.get('msgs', self.size_record_chat))
            self.recording[chat_id] = {'status': IDLE, 'msgs': deque(maxlen=size_record_chat)}
        # Update deque size
        new_size_msgs = int(records.get('msgs', self.size_record_chat))
        if new_size_msgs != self.recording[chat_id]['msgs'].maxlen:
            old_msgs = list(self.recording[chat_id]['msgs'])
            logger.info(f"Update msgs size from {self.recording[chat_id]['msgs'].maxlen} to {new_size_msgs}")
            # Update deque
            self.recording[chat_id]['msgs'] = deque(old_msgs, maxlen=new_size_msgs)
        # restart timer only if is active
        if 'job' in self.recording[chat_id] and self.recording[chat_id]['status'] in [WRITING]:
            # restart timer
            self.job_timer_reset(chat_id)
        return False

    def record_document(self, update, context):
        # Filter and update data channel
        if self.record_filter(update, context):
            return
        chat_id = update.effective_chat.id
        # Recording funcions
        if self.recording[chat_id]['status'] in [WRITING]:
            # Get file id picture big size
            file_id = update.message.document.file_id
            newFile = context.bot.get_file(file_id)
            # Get filename
            file_name = update.message.document.file_name
            # Add text
            text = f"Attached document: {file_name}"
            # Attention chat in absolute value !!!!!!!!!!!!!
            folder_name = str(chat_id)[1:]
            folder_record = self.recording[chat_id]['folder_record']
            # Path document
            document = f"{self.records_folder}/{folder_name}/{folder_record}/{file_name}"
            # Download the document
            newFile.download(document)
            # Make message
            msg = make_dict_message(update, text)
            # Add message in queue text
            self.recording[chat_id]['msgs'].append(msg)
            self.writing(context, chat_id, msg)

    def record_photo(self, update, context):
        # Filter and update data channel
        if self.record_filter(update, context):
            return
        chat_id = update.effective_chat.id
        # Recording funcions
        if self.recording[chat_id]['status'] in [WRITING]:
            # Get file id picture big size
            file_id = update.message.photo[-1]
            newFile = context.bot.get_file(file_id)
            # Get filename
            # https://stackoverflow.com/questions/10552188/python-split-url-to-find-image-name-and-extension
            picture_page = newFile.file_path
            disassembled = urlparse(picture_page)
            file_name = basename(disassembled.path)
            # Write text
            text = f"Attached photo {file_name}"
            if update.message.caption:
                text+= f" - Caption: {update.message.caption}"
            # Attention chat in absolute value !!!!!!!!!!!!!
            folder_name = str(chat_id)[1:]
            folder_record = self.recording[chat_id]['folder_record']
            # Path document
            document = f"{self.records_folder}/{folder_name}/{folder_record}/{file_name}"
            # Download the document
            newFile.download(document)
            # Make message
            msg = make_dict_message(update, text)
            # Add message in queue text
            self.recording[chat_id]['msgs'].append(msg)
            self.writing(context, chat_id, msg)

    def record(self, update, context):
        #if update.edit_message is not None:
        #    print(update.edit_message.text)
        # print(update.message)
        if update.message.reply_to_message:
            print(update.message.reply_to_message.message_id)
        # Filter and update data channel
        if self.record_filter(update, context):
            return
        chat_id = update.effective_chat.id
        # Text message
        text = update.message.text
        # Make message
        msg = make_dict_message(update, text)
        # Recording funcions
        if self.recording[chat_id]['status'] in [WRITING]:
            # Add message in queue text
            self.recording[chat_id]['msgs'].append(msg)
            self.writing(context, chat_id, msg)
        else:
            # Add message in queue text
            self.recording[chat_id]['msgs'].append(msg)
        # https://python-telegram-bot.readthedocs.io/en/latest/telegram.messageentity.html
        # entities = update.message.parse_entities()
        # Extract all hashtags
        hashtags = re.findall(r"#(\w+)", text)
        # check if there is the start hashtag
        start = True if START in hashtags else False
        stop = True if STOP in hashtags else False
        # Initialize recording
        chat_id = update.effective_chat.id
        # If start is only in this text start to record
        if start and self.recording[chat_id]['status'] == IDLE:
            # Wait reply
            self.recording[chat_id]['status'] = WAIT_START
            # Send message
            text = "📼 Do you want *record* this chat? 📼"
            self.recording[chat_id]['job_autoreply'] = Autoreply(self.updater, context, chat_id, 'REC_START', text, self.cb_start, 'false')
        elif stop and self.recording[chat_id]['status'] not in [IDLE, WAIT_START, WAIT_STOP]:
            # Remove and stop the timer
            self.job_timer_stop(chat_id)
            self.job_timer_delete(chat_id)
            # Send message
            text = "🚫 Do you want *stop* now? 🚫"
            self.recording[chat_id]['job_autoreply'] = Autoreply(self.updater, context, chat_id, 'REC_STOP', text, self.cb_stop, 'true')
        # Check before to start if require to wait
        if not self.recording[chat_id].get('delay_autorestart', False):
            # Auto record start
            self.auto_start(context, chat_id)

    def auto_start(self, context, chat_id):
        # Minimum number of messages recordered
        records = self.settings['config'].get('records', {})
        size_record_chat = int(records.get('msgs', self.size_record_chat))
        rush_messages = False
        if len(self.recording[chat_id]['msgs']) > size_record_chat // 2:
            # Get first and last message
            first = self.recording[chat_id]['msgs'][-size_record_chat // 2]
            last = self.recording[chat_id]['msgs'][-1]
            # print(f"First: {first['date']} - {first['text']} -- Last: {last['date']} - {last['text']}")
            # Measure delta from last and first message
            delta = last['date'] - first['date']
            # print(f"Delta: {delta}")
            # If delta is minus or equal the minimum time enable rush_messages
            records = self.settings['config'].get('records', {})
            min_delta = int(records.get('min_start', self.min_delta))
            if delta <= timedelta(minutes=min_delta):
                rush_messages = True
        # Run Autostart
        if rush_messages and self.recording[chat_id]['status'] == IDLE:
            # Wait reply
            self.recording[chat_id]['status'] = WAIT_START
            # Set autorestart
            self.recording[chat_id]['autorestart'] = True
            # Send message
            text = "🔥 This chat getting *hot* 🔥\n📼 Do you want *record* this chat? 📼"
            self.recording[chat_id]['job_autoreply'] = Autoreply(self.updater, context, chat_id, 'REC_START', text, self.cb_start, 'false')

    def writing(self, context, chat_id, msg):
        # Attention chat in absolute value !!!!!!!!!!!!!
        folder_name = str(chat_id)[1:]
        folder_record = self.recording[chat_id]['folder_record']
        file_name = self.recording[chat_id]['file_name']
        # Append new line on file
        with open(f"{self.records_folder}/{folder_name}/{folder_record}/{file_name}", "a") as f:
            data = [str(msg[name]) for name in MSG_TEXT_ORDER]
            f.write(f"{self.separator}".join(data) + f"\n")
        # log status
        logger.info(f"Chat {chat_id} in WRITING {msg['text']}")

    def init_record(self, context, chat_id):
        # Attention chat in absolute value !!!!!!!!!!!!!
        folder_name = str(chat_id)[1:]
        last_record = self.recording[chat_id]['msgs'][-1]
        # Make new folder and file name
        folder_record = str(last_record['date'].timestamp()).split('.')[0]
        self.recording[chat_id]['folder_record'] = folder_record
        file_name = str(last_record['date']) + "." + self.extension
        self.recording[chat_id]['file_name'] = file_name
        # Make chat folder if not exist
        if not os.path.isdir(f"{self.records_folder}/{folder_name}"):
            os.mkdir(f"{self.records_folder}/{folder_name}")
            logger.info(f"Chat directory {folder_name} created")
        # Make record folder
        if not os.path.isdir(f"{self.records_folder}/{folder_name}/{folder_record}"):
            os.mkdir(f"{self.records_folder}/{folder_name}/{folder_record}")
            logger.info(f"Record directory {folder_record} created")
        # Init file and write a file
        # "x" - Create - will create a file, returns an error if the file exist
        # "a" - Append - will create a file if the specified file does not exist
        # "w" - Write - will create a file if the specified file does not exist
        with open(f"{self.records_folder}/{folder_name}/{folder_record}/{file_name}", "x") as f:
            # Write header
            f.write(f"{self.separator}".join(MSG_TEXT_ORDER) + f"\n")
            # Copy all messages
            for msg in self.recording[chat_id]['msgs']:
                data = [str(msg[name]) for name in MSG_TEXT_ORDER]
                f.write(f"{self.separator}".join(data) + f"\n")
        # log status
        logger.info(f"Chat {chat_id} in WRITING")

    def idle(self, bot, chat_id):
        # Clear message list
        self.recording[chat_id]['msgs'].clear()
        # log status
        logger.info(f"Chat {chat_id} in IDLE")
        # Extract msgs
        # Attention chat in absolute value !!!!!!!!!!!!!
        folder_name = str(chat_id)[1:]
        folder_record = self.recording[chat_id]['folder_record']
        # Send recordered registration
        self.send_record(bot, chat_id, folder_name, folder_record)

    def timer_stop(self, context: CallbackContext):
        # Extract chat ids
        chat_id = context.job.context
        # Wait reply
        self.recording[chat_id]['status'] = WAIT_STOP
        # Send message
        text = "*TOK TOK* There is anyone here?\n🚫 Do you want *stop* now? 🚫"
        self.recording[chat_id]['job_autoreply'] = Autoreply(self.updater, context, chat_id, 'REC_TIMER_STOP', text, self.cb_stop, 'true', keyID=chat_id)

    @check_key_id('Error message')
    def start(self, update, context):
        query = update.callback_query
        data = query.data.split()
        # Extract keyID
        keyID = data[1]
        chat_id = context.user_data[keyID]['chat_id']
        # Start controller callback
        self.cb_start(context, query.message.message_id, chat_id, data)
        # remove key from user_data list
        del context.user_data[keyID]

    def cb_start(self, context, message_id, chat_id, data):
        # Stop the autoreply timer
        if chat_id in self.recording:
            if 'job_autoreply' in self.recording[chat_id]:
                self.recording[chat_id]['job_autoreply'].stop()
            # Extract status record
            status = True if data[2] == 'true' else False
            if status:
                # Start write mode
                self.init_record(context, chat_id)
                # Start timer
                self.job_timer_start(chat_id)
                # Initialize writing mode
                self.recording[chat_id]['status'] = WRITING
                # Clear wait autorestart
                if 'delay_autorestart' in self.recording[chat_id]:
                    self.recording[chat_id]['delay_autorestart'] = False
                # Stop the timer
                if 'job_delay_autorestart' in self.recording[chat_id]:
                    job = self.recording[chat_id]['job_delay_autorestart']
                    job.enabled = False  # Temporarily disable this job
                    job.schedule_removal()  # Remove this job completely
                # Message to send
                text = f"📼 *Recording*..."
                context.bot.edit_message_text(chat_id=chat_id, text=text, message_id=message_id, parse_mode='Markdown')
            else:
                self.recording[chat_id]['status'] = IDLE
                # Clear wait autorestart
                if 'autorestart' in self.recording[chat_id]:
                    if self.recording[chat_id]['autorestart']:
                        self.recording[chat_id]['delay_autorestart'] = True
                # Send the message
                text = f"Ok next time!"
                context.bot.edit_message_text(chat_id=chat_id, text=text, message_id=message_id, parse_mode='Markdown')
            # Clear autorestart status
            if 'autorestart' in self.recording[chat_id]:
                self.recording[chat_id]['autorestart'] = False
            # Run delay autorestart
            if self.recording[chat_id].get('delay_autorestart', False):
                records = self.settings['config'].get('records', {})
                d_start = int(records.get('d_start', self.d_start))
                logger.info(f"Delay autorestart chat: {chat_id} for {d_start}s")
                self.recording[chat_id]['job_delay_autorestart'] = self.job.run_once(self.reset_delay_autorestart, d_start, context=chat_id)
        else:
            text = "Error message"
            context.bot.edit_message_text(chat_id=chat_id, text=text, message_id=message_id, parse_mode='Markdown')

    def reset_delay_autorestart(self, context: CallbackContext):
        # Extract chat ids
        chat_id = context.job.context
        # Clear wait autorestart
        if 'delay_autorestart' in self.recording[chat_id]:
            self.recording[chat_id]['delay_autorestart'] = False
        logger.info(f"Reset delay autorestart chat: {chat_id}")

    @check_key_id('Error message')
    def stop(self, update, context):
        query = update.callback_query
        data = query.data.split()
        # Extract keyID
        keyID = data[1]
        chat_id = context.user_data[keyID]['chat_id']
        # Run callback stop
        self.cb_stop(context, query.message.message_id, chat_id, data)
        # remove key from user_data list
        del context.user_data[keyID]

    def timer_stop_cb(self, update, context):
        query = update.callback_query
        data = query.data.split()
        chat_id = int(data[1])
        # Run callback stop
        self.cb_stop(context, query.message.message_id, chat_id, data)

    def cb_stop(self, context, message_id, chat_id, data):
        # Stop the autoreply timer
        if chat_id in self.recording:
            if 'job_autoreply' in self.recording[chat_id]:
                self.recording[chat_id]['job_autoreply'].stop()
            # Extract status record
            status = True if data[2] == 'true' else False
            if status:
                # Remove and stop the timer
                self.job_timer_stop(chat_id)
                self.job_timer_delete(chat_id)
                # Set in idle mode and wait a new record
                self.idle(context.bot, chat_id)
                # Set in idle mode
                self.recording[chat_id]['status'] = IDLE
                # Send message
                text = f"🛑 Recording *stop*!"
                context.bot.edit_message_text(chat_id=chat_id, text=text, message_id=message_id, parse_mode='Markdown')
            else:
                # Start timer
                self.job_timer_reset(chat_id)
                # Send the message
                text = f"📼 *Recording*..."
                context.bot.edit_message_text(chat_id=chat_id, text=text, message_id=message_id, parse_mode='Markdown')
        else:
            text = "Error message"
            context.bot.edit_message_text(chat_id=chat_id, text=text, message_id=message_id, parse_mode='Markdown')