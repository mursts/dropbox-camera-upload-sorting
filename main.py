#!/usr/bin/env python
# coding: utf-8

import hmac
import logging
import os
import threading
from hashlib import sha256

import dropbox
from dropbox.files import DeletedMetadata, FolderMetadata
from flask import Flask, abort, request, Response
from google.cloud import datastore

import config

# 変更監視ディレクトリ
WATCH_DIR = '/Camera Uploads'
# 移動先ディレクトリ
SAVE_DIR = '/_Mobile_Camera_Uploads'
# Datastore Key
DATASTORE_KEY = 'cursor'
DATASTORE_KIND_NAME = 'DBXWebhookCursor1'

app = Flask(__name__)
app.secret_key = os.urandom(24)


def make_file_path(file_path):
    """
    保存するパスの形式に変換します
    from: yyyy-mm-dd hh.mm.dd.jpg
    to  : yyyy-mm/yyyy-mm.dd_hh.mm.dd.jpg
    :param file_path:
    """
    file_name = file_path.split('/')[-1]
    file_name = file_name.replace(' ', '_')
    dir_name = file_name[0:7]

    return dir_name + '/' + file_name


def execute():
    ds_client = datastore.Client()
    try:
        key = ds_client.key(DATASTORE_KIND_NAME, DATASTORE_KEY)
        entity = ds_client.get(key)

        dbx = dropbox.Dropbox(config.access_token)

        has_more = True

        while has_more:
            if entity is None:
                result = dbx.files_list_folder(path=WATCH_DIR)
            else:
                c = entity['cursor']
                result = dbx.files_list_folder_continue(c)

            for entry in result.entries:
                logging.debug(entry)
                if isinstance(entry, DeletedMetadata) or isinstance(entry, FolderMetadata):
                    continue

                dest = os.path.join(SAVE_DIR, make_file_path(entry.path_lower))

                dbx.files_move_v2(entry.path_lower, dest)

            cursor = result.cursor

            entity = datastore.Entity(key=key)
            entity.update({'cursor': cursor})
            ds_client.put(entity)

            has_more = result.has_more
    except Exception as e:
        logging.error(e)


def validate_request():
    signature = request.headers.get('X-Dropbox-Signature')
    return signature == hmac.new(config.app_secret.encode('utf-8'), request.data, sha256).hexdigest()


@app.route('/webhook', methods=['GET'])
def challenge():
    resp = Response(request.args.get('challenge'))
    resp.headers['Content-Type'] = 'text/plain'
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    return resp


@app.route('/webhook', methods=['POST'])
def webhook():
    if not validate_request():
        abort(403)

    threading.Thread(target=execute).start()

    return ''


if __name__ == '__main__':
    debug = False
    if os.getenv('GAE_ENV', '').startswith('localdev'):
        debug = True
    app.run(host='127.0.0.1', port=8080, debug=debug)
