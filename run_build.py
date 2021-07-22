import re
import sys
import subprocess
import functools
import urllib.request
import shutil
import os
import smtplib
import json
import multiprocessing
from pathlib import Path
from email.message import EmailMessage
from typing import List, Dict, Any

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
    # Example: v1 = "5.12" vs. v2 = "5.12.1" (this actually happens; I hope they don't omit ".0" !)
    elif len(v1) > len(v2):
        return 1
    # the other way around
    else:
        return -1

def find_built_ver() -> str:
    with open("config", "r") as f:
        lines: List[str] = f.readlines()

        for l in lines:
            m = re.match(r"# Linux/x86 ([0-9\.]+) Kernel Configuration", l)
            if m is not None:
                return m.group(1)

        raise(ValueError("The version info cannot be extracted from the `config' file"))

def find_latest_ver(lock_ver: str) -> str:
    REPO_URL: str = "https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git"
    git_ls_remote: List[str] = subprocess.check_output(["git", "ls-remote", "--tags", "--ref", REPO_URL], text=True, stderr=subprocess.DEVNULL).split('\n')[:-1]
    avail_vers: List[str] = []

    for s in git_ls_remote:
        m = re.match(r"[0-9a-f]*\trefs/tags/v(.*)", s)
        if m is not None: # re.match returns None if there is no match
            v = m.group(1)
            # exclude non "complete" versions (e.g., 5.10-rc1, 5.10.0-tree) and
            # versions that do not start with `lock_ver'
            if v.find("-") == -1 and v.startswith(lock_ver):
                avail_vers.append(v)

    return sorted(avail_vers, key=functools.cmp_to_key(newer))[-1]

def create_url(v: str) -> str:
    URL_BASE: str = "https://cdn.kernel.org/pub/linux/kernel/v"
    major_ver: str = v.split('.')[0]

    # Ex: https://cdn.kernel.org/pub/linux/kernel/v5.x/linux-5.11.15.tar.xz
    return URL_BASE + major_ver + ".x/linux-" + v + ".tar.xz"

def do_build(v: str, n_jobs: int) -> bool:
    url: str = create_url(v)
    dirname: str = "linux-" + v
    filename: str = dirname + ".tar.xz"

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
        shutil.copyfile(dirname + "/.config", "config")   # copy the latest config back
        force_delete(filename)
        force_delete(dirname)
        return True
    else:
        return False

def notify(ver: str, mail_config: Dict[str, str]):
    msg = EmailMessage()
    msg['Subject'] = ('New kernel was successfully built: ' + ver)
    msg['From'] = mail_config["from_addr"]
    msg['To'] = mail_config["to_addr"]

    s = smtplib.SMTP(mail_config["server_addr"], int(mail_config["port"]))
    s.starttls()
    s.login(mail_config["user"], mail_config["password"])
    s.send_message(msg)

def retrieve_config(setting: Dict[str, Any], key: str, default):
    if key in setting:
        return setting[key]
    else:
        return default

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: {} setting".format(sys.argv[0]))
        sys.exit(1)

    with open(sys.argv[1], "r") as f:
        setting: Dict[str, Any] = json.load(f)

    lock_ver: str = retrieve_config(setting, "lock_ver", "")
    latest_ver: str = find_latest_ver(lock_ver)
    built_ver: str = find_built_ver()
    n_jobs: int = retrieve_config(setting, "n_jobs", multiprocessing.cpu_count() - 1)

    if newer(latest_ver, built_ver) > 0:
        print("A new version available:", latest_ver)

        ret: bool = do_build(latest_ver, n_jobs)
        if ret:
            print("Build success!")
        else:
            print("An error occured while buidling. Please check out the log.")            

        if "mail_config" in setting:
            notify(latest_ver, setting["mail_config"])
    else:
        print("No new version is available (built: {}, latest: {}).".format(built_ver, latest_ver))
