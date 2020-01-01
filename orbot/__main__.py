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

import telegram
import json
import argparse
# Drive manager
from .drive import Drive
# Load ORbot
from .orbot import ORbot


def main():
    parser = argparse.ArgumentParser(description='Officine Robotiche bot manager')
    parser.add_argument('-s', dest="settings", help='path of setting file', default='config/settings.json')
    # Google Drive
    #drive = Drive(settings['drive'])
    #drive.testDrive()
    #drive.upload()
    # Parse arguments
    args = parser.parse_args()
    # Load settings
    with open(args.settings) as stream:
        settings = json.load(stream)
    # Run telegram bot
    if 'telegram' in settings:
        # load bot
        telebot = settings['telegram']
        bot = telegram.Bot(token=telebot['token'])
        # Load information bot
        infobot = bot.get_me()
        print("Bot info:")
        print(" - name:", infobot["first_name"])
        print(" - username:", infobot["username"])
        print(" - ID:", infobot["id"])
    # Telegram ORbot
    orbot = ORbot(args.settings)
    print("ORbot started")
    # Run the bot
    orbot.runner()


if __name__ == "__main__":
    main()
# EOF
