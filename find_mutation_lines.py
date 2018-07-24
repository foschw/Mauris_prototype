#!/usr/bin/env python3
import sys
sys.path.append('.')
import taintedstr
import pickle
import re
import argtracer
import functools
from argtracer import get_code_from_file, extract_from_condition
from argtracer import Timeout as Timeout
import random
import os
import glob
import imp

RE_raise = re.compile(r'(^|\s+)raise\s+')

@functools.lru_cache(maxsize=None)
def was_manually_raised(file, lineno):
    return True if RE_raise.search(get_code_from_file(file, lineno)) else False

def get_left_diff(l1, l2):
    prim = []
    sec = []
    lns = [i[0] for i in l2]
    for e in l1:
        if e not in l2 and e not in prim and e not in sec:
            if e[0] in lns:
                prim.append(e)
            else:
                sec.append(e)
            
    return (prim, sec)

def sanitize(valuestring):
    return repr(valuestring)

def list_from_dict(cond_dict, unpack):
    clines = []
    for lne in cond_dict.keys():
        bval = cond_dict[lne]
        if len(bval) == 1:
            clines.append((lne, cond_dict[lne].pop()))
        elif unpack and len(bval) == 2:
            clines.append((lne, True))
            clines.append((lne, False))
    return clines


def make_new_conditions(old_cond, file, b_varsat, varsat):
    (lineno, state) = old_cond
    full_str = get_code_from_file(file, lineno)
    cond_str = extract_from_condition(full_str)
    # Conditions that hold for the last execution of the line and not for the baseline run
    lcand = varsat.get(lineno) if varsat.get(lineno) else None
    if lcand:
        rcand = b_varsat[lineno] if b_varsat.get(lineno) else []
    else: return None

    choices = [i for i in lcand if i not in rcand]
    stable = {}
    for i in choices:
        stable[i[0]] = i[1] if not stable.get(i[0]) or stable.get(i[0]) == i[1] else -1
    stable = [i for i in choices if type(stable[i[0]]) != type(1)]
    print("Possible choices:", choices)
    print("Stable choices:", stable)
    valid_cond = random.choice(stable) if stable else random.choice(choices)
    if state:
        # Falsify the condition
        valid_cond = valid_cond[0] + " != " + sanitize(valid_cond[1])
        new_cond = "(" + cond_str + ") and " + valid_cond
    else:
        # Satisfy the condition
        valid_cond = valid_cond[0] + " == " + sanitize(valid_cond[1])
        new_cond = "(" + cond_str + ") or " + valid_cond
        
    cond_idx = full_str.find(cond_str)
    nc1 = full_str[0:cond_idx] + new_cond + full_str[cond_idx+len(cond_str):]
    nc2 = full_str[0:cond_idx] + valid_cond + full_str[cond_idx+len(cond_str):]
    return (str(nc1), str(nc2))

def get_possible_fixes(delta, file, b_varsat, varsat):
    (prim, sec) = delta
    fixmap = []
    if prim:
        for (lineno, state) in prim:
            cand = make_new_conditions((lineno,state),file,b_varsat,varsat)
            if cand: fixmap.append((lineno, cand))
    elif sec:
        for (lineno, state) in sec:
            cand = make_new_conditions((lineno,state),file,b_varsat,varsat)
            if cand: fixmap.append((lineno, cand))
    return fixmap

def file_copy_replace(target, source, modifications):
    with open(target, "w", encoding="UTF-8") as trgt:
        with open(source, "r", encoding="UTF-8") as src:
            for i, line in enumerate(src):
                if modifications.get(i+1):
                    trgt.write(modifications[i+1])
                else:
                    trgt.write(line)

def cleanup(mut_dir, completed):
    for fl in glob.glob(mut_dir + "/*.py"):
        fl = fl.replace("\\", "/")
        if fl not in completed:
            os.remove(fl)

if __name__ == "__main__":
    arg = sys.argv[1]
    arg = arg.replace("\\", "/")
    ar1 = arg
    mut_dir = arg[arg.rfind("/")+1:arg.rfind(".")] if arg.rfind("/") >= 0 else arg[:arg.rfind(".")]
    script_name = mut_dir
    mut_dir = "mutants/" + mut_dir + "/"
    # Timeout since our modifications may cause infinite loops
    timeout = 5
    if not os.path.exists(mut_dir):
        os.makedirs(mut_dir)
    else:
        cleanup(mut_dir, [])

    # Index of the string currently processed
    str_cnt = 0
    # Mutation counter
    mut_cnt = 0
    pick_file = sys.argv[2] if len(sys.argv) > 2 else "rejected.bin"
    pick_handle = open(pick_file, 'rb')
    rej_strs = pickle.load(pick_handle)

    # Get base values from the non-crashing run with the longest input
    basein = ""
    for cand in rej_strs:
        basein = cand[1] if len(cand[1]) > len(basein) else basein
    try:
        (_, b_clines, b_vrs, _) = argtracer.trace(arg, basein, timeout=timeout)
        b_clines = list_from_dict(b_clines, False)
    except Timeout:
        print("Execution timed out on basestring! Try increasing timeout (currently", timeout," seconds)")

    print("Used baseinput:", repr(basein))

    for s in rej_strs:
        s = s[0]
        queue = [(ar1, [])]
        discarded = set()
        while queue:
            print("Entering loop...")
            (arg, history) = queue.pop(0)
            # Check whether the chosen correct string is now rejected
            try:
                _mod = imp.load_source('mymod', arg)
            except:
                print("Discarded script:", arg)
                discarded.add(arg)
                continue
            print("Executing basestring...")
            try:
                (_, _, _, berr) = argtracer.trace(arg, basein, timeout=timeout)
            except argtracer.Timeout:
                print("Discarding,", arg, "due to timeout")
                discarded.add(arg)
                continue
            print("Base done.")
            # Mutation guided by rejected strings

            try:
                (lines, clines, vrs, err) = argtracer.trace(arg, s, timeout=timeout)
                clines = list_from_dict(clines, True)
            except argtracer.Timeout:
                discarded.add(arg)
                continue

            (prim, sec) = get_left_diff(clines, b_clines) if not berr else ([],[])
            print("Current script:", arg)
            print("Used string:", repr(s))
            print("Difference to base (flipped):", prim)
            print("Difference to base (new):", sec)
            print("Final line:", str(lines[0]))
            print("")
            print("Change history:", history)
            print("Base rejected:", berr)
            prim = [e for e in prim if e[0] not in history]
            sec = [e for e in sec if e[0] not in history]
            if not berr and err and (was_manually_raised(arg, lines[0])):
                discarded.add(arg)
                for (linenum, fixes) in get_possible_fixes((prim, sec), arg, b_vrs, vrs):
                    for fix in fixes:
                        cand = mut_dir + script_name + "_" + str(str_cnt) + "_" + str(mut_cnt) + ".py"
                        mods = {
                            linenum : fix
                            }
                        queue.append((cand, history.copy()+[linenum]))
                        file_copy_replace(cand, arg, mods)
                        mut_cnt += 1
            else:
                print("Base rejected:", berr, ", manual:", was_manually_raised(arg, lines[0]))
                print("Mutation complete:", arg)
        discarded.discard(ar1)
        for scrpt in discarded:
            print("Removed:", scrpt)
            os.remove(scrpt)
        str_cnt += 1
        mut_cnt = 0
        print("Processing string number:", str(str_cnt), "/", str(len(rej_strs)))
    print("Done. The final mutants are in:", mut_dir)
    with open("mutants/lastrun.py", "w", encoding="UTF-8") as file:
            for i in range(len(rej_strs)):
                file.write(str(i) + ": " + repr(rej_strs[i][0])+"\n")
            file.write("The baseinput was:" + repr(basein))
