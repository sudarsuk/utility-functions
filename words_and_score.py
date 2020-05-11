import os
import re
import cv2
import json
import PIL.Image
import traceback
import subprocess
import numpy as np
import tempfile
import datetime
from logging import warning
from scipy.ndimage import interpolation
import textdistance


def seperate_last_element(image_path):
    img = cv2.imread(image_path)
    file_name = image_path.rsplit("/")[-1].split('.')[0]
    (h, w) = img.shape[:2]
    mser = cv2.MSER_create()
    # Identify the largest object
    mser.setMaxArea((h * w) // 2)
    mser.setMinArea(30)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    _, bw = cv2.threshold(gray, 0.0, 255.0, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    _, rects = mser.detectRegions(bw)

    # find max value in rects -> find last point element in image
    # max_num = np.amax(rects)

    # print(rects, '   rects')

    max_num = 0
    for i in rects:
        if i[0] > max_num:
            max_num = i[0]

    # print(max_num, '    max_num')

    super_script = None
    word_start_point = None
    word_end_point = None
    temp_list = []

    for idx, i in enumerate(rects):
        # find super script or last element
        if rects[idx][0] == max_num:
            super_script = rects[idx]
            continue
        # find last element -> some not simple image
        elif rects[idx][1] == max_num or rects[idx][2] == max_num or rects[idx][3] == max_num:
            super_script = rects[1]
            temp_list.append(list(rects[0]))
        # witout last element words
        else:
            temp_list.append(list(rects[idx]))
    
    # print(temp_list)
    
    container = []
    for i in temp_list:
        container.append(i[0])

    mini = min(container)
    maxi = max(container)

    # print(mini, '  mini')
    # print(maxi, '  maxi')

    # min = temp_list[0][0] # random min value
    # max = temp_list[-1][0]  # random max value
    ch_height = temp_list[0][3] # char width value

    # find start point of word, end point of word and the highest character
    for i in temp_list:
        if i[0] < mini or i[0] == mini:
            mini = i[0]
            word_start_point = i
        if i[0] > maxi or i[0] == maxi:
            maxi = i[0]
            word_end_point = i
        if i[3] > ch_height:
            ch_height = i[3]

    # crop image without superscript or last element
    left, top  = int(word_start_point[0]), int(word_start_point[1]) 
    width, height = int(word_end_point[0]) + int(word_end_point[2]) + int(1), int(word_end_point[1]) + int(ch_height)

    croped_img = img[top: height,  left: width]
    img_result = cv2.copyMakeBorder(croped_img, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=[255, 255, 255])
    temp_dir = tempfile.mkdtemp()
    word_image_path = "%s/word-%s.jpg" % (temp_dir, file_name)
    cv2.imwrite("%s" % word_image_path, img_result)

    output_tsv_word = run("tesseract %s - -l mon --psm 8 tsv" % word_image_path)
    res = second_parse_tsv(output_tsv_word)

    # crop superscript or last element
    # left, top = int(super_script[0]), int(super_script[1])
    # width, height = int(super_script[2]), int(super_script[3])

    # crop_s_script = img[top: top + height, left: left + width]
    # s_script_result = cv2.copyMakeBorder(crop_s_script, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=[255, 255, 255])
    # # zoom in on s_script_result
    # width = int(s_script_result.shape[1] * 3)
    # height = int(s_script_result.shape[0] * 3) 
    # resized = cv2.resize(s_script_result, (width, height), interpolation = cv2.INTER_AREA)
    # last_image_path = "%s/last-%s.jpg" % (temp_dir, file_name)
    # cv2.imwrite("%s" % last_image_path, resized)

    return res


def cleanWord(word):
    if word.startswith('"'):
        word = word.replace('"', '')
    if word.endswith('"'):
        word = word.replace('"', '')
    if word.startswith('“'):
        word = word.replace('”', '')
    if word.endswith('”'):
        word = word.replace('”', '')
    if word.endswith('.'):
        word = word.replace('.', '')
    if word.endswith(','):
        word = word.replace(',', '')
    return word.strip()


def words_and_scores(output_tsv, image_path):
    result = []
    parsed = second_parse_tsv(output_tsv)
    img = cv2.imread(image_path)
    current_block = "1"

    dict_en = set(file_read("./dict_en.txt").strip().split("\n"))
    dict_mn = set(file_read("./dict_mn.txt").strip().split("\n"))

    for idx, r in enumerate(parsed):
        # Type: newline
        if current_block != r["block_num"]:
            result.append({
                "type": "newline",
                "word": "\n\n",
                "score": 100,
            })
            current_block = r["block_num"]

        # Type: mn:by_score
        if int(r["conf"]) >= 90:
            result.append({
                "type": "mn:by_score",
                "word": r["text"],
                "score": int(r["conf"]),
            })
            continue

        # Type: mn:by_in_dict
        if int(r["conf"]) >= 50 and r["text"] in dict_mn:
            result.append({
                "type": "mn:by_in_dict",
                "word": r["text"],
                "score": int(r["conf"]),
            })
            continue
        # endfold

        # word coordinates
        left, top = int(r["left"]), int(r["top"])
        width, height = int(r["width"]), int(r["height"])

        # crop and add padding
        img_result = img[top: top + height, left: left + width]
        h,w = img_result.shape[:2]
        if int(w) < int(10):
            continue
        else:
            img_result = cv2.copyMakeBorder(img_result, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=[255, 255, 255])

            temp_dir = tempfile.mkdtemp()
            temp_image_path = "%s/%s.jpg" % (temp_dir, str(idx))
            cv2.imwrite("%s" % temp_image_path, img_result)
            # print(temp_image_path, '  temp_image_path')
            # output_image_path = "./output_pics/%s.jpg" % str(idx)
            # cv2.imwrite("%s" % output_image_path, img_result)

            # seperate last element
            
            # result of tesseract eng
            output_tsv_eng = run("tesseract %s - -l eng --psm 8 tsv" % temp_image_path)
            # output_tsv_eng = run("tesseract %s - -l eng --psm 8 tsv" % output_image_path)
            t = second_parse_tsv(output_tsv_eng)

            # Type: en:by_score
            if t and int(t[0]["conf"]) >= 90:
                result.append({
                    "type": "en:by_score",
                    "word": t[0]["text"],
                    "score": int(t[0]["conf"]),
                    "verbose": {
                        "mon": {
                            "word": r["text"],
                            "score": int(r["conf"]),
                        },
                    },
                })
                continue

            # Type: en:by_in_dict
            if t and t[0]["text"] in dict_en:
                result.append({
                    "type": "en:by_in_dict",
                    "word": t[0]["text"],
                    "score": int(t[0]["conf"]),
                    "verbose": {
                        "mon": {
                            "word": r["text"],
                            "score": int(r["conf"]),
                        },
                    },
                })
                continue
            # endfold
            # # Type: mn:by_in_dict after clean dot and comma
            if t and int(t[0]["conf"]) < int(r["conf"]):
                result_word = cleanWord(r["text"])
                if result_word in dict_mn:
                    result.append({
                        "type": "mn:by_in_dict",
                        "word": result_word,
                        "score": int(r["conf"]),
                    })
                    continue
            # image seperate last char and tesseract
            if t:
                word = seperate_last_element(temp_image_path)
                if word[0]["text"] in dict_mn:
                    result.append({
                        "type": "mn:by_in_dict",
                        "word": word[0]["text"],
                        "score": int(r["conf"]),
                    })
                    continue

            if t and int(t[0]["conf"]) > int(r["conf"]):
                max_score = t[0]
            else:
                max_score = r
                print(' ene in else', r)

            result.append({
                "type": "fail",
                "word": max_score["text"],
                "score": int(max_score["conf"]),
                "verbose": {
                    "eng": {
                        "word": t[0]["text"] if t else "",
                        "score": int(t[0]["conf"]) if t else 0,
                    },
                    "mon": {
                        "word": r["text"],
                        "score": int(r["conf"]),
                    },
                },
            })
    return result

def file_read(path, format=None, default=None):
    if os.path.exists(path):
        with open(path) as f:
            result = f.read()
    else:
        result = default

    if format == "json":
        result = json.loads(result)

    return result

def second_parse_tsv(tsv_input):
    result = []
    headers = []
    for line in tsv_input.strip().split("\n"):
        parsed = line.split("\t")
        if not headers:
            headers = parsed
            continue
        if len(headers) != len(parsed):
            parsed.append("")

        # exclude non-word items
        if parsed[0] != "5":
            continue

        # skip whitespaces only word
        if parsed[-1].strip() == "":
            continue
        result.append(dict(zip(headers, parsed)))
    return result

def run(command):
    scripts = getattr(run, "scripts", "./scripts")
    command = command.replace("{scripts}", scripts)

    debug = getattr(run, "debug", "")
    if debug:
        print("[run] command: %r" % command)

    cmd_args = command.split()
    params = {
        "check": True,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.DEVNULL,
        "universal_newlines": True,
    }
    try:
        process = subprocess.run(cmd_args, **params)
    except subprocess.CalledProcessError as exc:
        print(exc)
        print(command)
        raise exc

    return process.stdout

if __name__ == '__main__':
    image_path = "./1588866156-1233.jpg"
    tsv_output = run("tesseract %s - -l mon tsv --tessdata-dir /usr/local/Cellar/tesseract-lang/4.0.0/share/tessdata/nom.traineddata" % image_path)

    words_and_scores(tsv_output, image_path)
