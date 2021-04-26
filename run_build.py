import re
import subprocess
import functools
import urllib.request
import shutil
import os
import smtplib
from pathlib import Path
from email.message import EmailMessage
from typing import List, Match

def force_delete(path: str):
    try:
        Path(path).unlink()
    except IsADirectoryError:
        shutil.rmtree(path)
    except FileNotFoundError:
        pass

# compares if v1 is newer than v2
def newer(v1: str, v2: str) -> int:
    # compare the version numbers
    for vv in zip(v1.split('.'), v2.split('.')):
        if int(vv[0]) > int(vv[1]):
            return 1
        elif int(vv[0]) < int(vv[1]):
            return -1

    # v1 and v2 are exactly the same
    if len(v1) == len(v2):
        return 0
    # if v1 is the same as v2 up to len(v2) and still has something, probably v1 is newer
    # Example: v1 = "5.4.10.1" vs. v2 = "5.4.10"
    elif len(v1) > len(v2):
        return 1
    # the other way around
    else:
        return -1

def get_lock_ver() -> str:
    try:
        with open("./lockfile", "r") as f:
            return f.readline().split("\n")[0] # remove tailing '\n'
    except FileNotFoundError:
        # if the lockfile does not exit, returns an empty string
        return ""

def find_latest_ver(lock_ver: str) -> str:
    git_ls_remote: List[str] = subprocess.check_output(["git", "ls-remote", "--tags", "--ref"], text=True, cwd="./git", stderr=subprocess.DEVNULL).split('\n')[:-1]
    avail_vers: List[str] = []

    for s in git_ls_remote:
        m = re.match(r"[0-9a-f]*\trefs/tags/v(.*)", s)
        if m is not None: # re.match returns None if there is no match
            v = m.group(1)
            # exclude non "complete" versions (e.g., 5.10-rc1, 5.10.0-tree) and
            # verions do not match lock_ver
            if v.find("-") == -1 and v.startswith(lock_ver):
                avail_vers.append(v)

    return sorted(avail_vers, key=functools.cmp_to_key(newer))[-1]

def get_built_ver() -> str:
    with open("./built_version", "r") as f:
        return f.readline().split("\n")[0] # remove tailing '\n'

def create_url(v: str) -> str:
    URL_BASE: str = "https://cdn.kernel.org/pub/linux/kernel/v"
    major_ver: str = v.split('.')[0]

    # Ex: https://cdn.kernel.org/pub/linux/kernel/v5.x/linux-5.11.15.tar.xz
    return URL_BASE + major_ver + ".x/linux-" + v + ".tar.xz"

def do_build(v: str):
    url: str = create_url(v)
    dirname: str = "linux-" + v
    filename: str = dirname + ".tar.xz"
    n_jobs: int = 3

    print("Download the kernel source from kernel.org")
    try:
        os.stat(filename)
        print(filename, "already exists.")
    except FileNotFoundError:
        with urllib.request.urlopen(url) as response:
            with open(filename, "wb") as f_archive:
                shutil.copyfileobj(response, f_archive)

    print("Extracing the archive")
    try:
        os.stat(dirname)
        print(dirname, "already exists.")
    except FileNotFoundError:
        subprocess.run(["tar", "xvf", filename], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # cp config $dirname/.config
    # yes "" | make oldconfig
    shutil.copyfile("config", dirname + "/.config")
    yes: subprocess.Popen[str] = subprocess.Popen(["yes", ""], stdout=subprocess.PIPE, text=True)
    subprocess.run(["make", "oldconfig"], stdin=yes.stdout, stdout=subprocess.DEVNULL, cwd=dirname, text=True)

    print("Executing make...")
    output: str = subprocess.check_output(["make", "bindeb-pkg", "-j", str(n_jobs)], stderr=subprocess.STDOUT, cwd=dirname, text=True)
    with open("run_build.log", "w") as f:
        f.write(output)

    if output.find("error:") == -1 and output.find("Error:") == -1:
        print("Build success!")
        shutil.copyfile(dirname + "/.config", "config")   # copy the latest config back
        with open("built_version", "w") as f:             # remember v as the latest built version
            f.write(str(v))
        force_delete(filename)
        force_delete(dirname)
    else:
        print("An error occured while buidling. Please check out the log.")

def notify(ver: str):
    try:
        with open("mail_config") as f:
            to_addr: str = f.readline().split("\n")[0]
            from_addr: str = f.readline().split("\n")[0]
            server_addr: str = f.readline().split("\n")[0]
            user: str = f.readline().split("\n")[0]
            pswd: str = f.readline().split("\n")[0]
            port: int = int(f.readline().split("\n")[0])
    except FileNotFoundError:
        # do nothing if mail_config does not exit
        return

    msg = EmailMessage()
    msg['Subject'] = ('New kernel was successfully built: ' + ver)
    msg['From'] = from_addr
    msg['To'] = to_addr

    s = smtplib.SMTP(server_addr, port)
    s.starttls()
    s.login(user, pswd)
    s.send_message(msg)

if __name__ == "__main__":
    lock_ver: str = get_lock_ver()
    latest_ver: str = find_latest_ver(lock_ver)
    built_ver: str = get_built_ver()

    if newer(latest_ver, built_ver) > 0:
        print("A new version available:", latest_ver)
        do_build(latest_ver)
        notify(latest_ver)
    else:
        print("No new version is available.")
