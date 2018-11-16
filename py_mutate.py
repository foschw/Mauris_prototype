#!/usr/bin/env python3
import sys
import getopt
sys.path.append('.')
from generate_reject import main as gen
from find_mutation_lines import main as mutate
from check_results import main as check

def main(argv):
    # The argument order is: program path, binary input file, number of pychains iterations
    prog = argv[1] if argv[1].endswith(".py") else argv[1] + ".py"
    binfile = "rejected_" + prog[prog.rfind("/")+1:prog.rfind(".py")] + ".bin" if not argv[2] else argv[2]
    timelimit = 60 if not argv[3] else argv[3]
    # Generate inputs in case no binary file is supplied
    if not argv[2]:
        print("Generating input for:", prog, "...", flush=True)
        gen([None, prog, timelimit, binfile])
    # Otherwise use the given inputs
    else:
        print("Using inputs from:", binfile, flush=True)
    print("Starting mutation...", prog, flush=True)
    # Run the mutation algorithm
    mutate([None, prog, binfile])
    # Finally check whether the results are fine.
    print("Testing result integrity...", flush=True)
    check([None, prog, binfile, True])

if __name__ == "__main__":
    print('The arguments are: "program path" [, -b "binary input file", -t "time for generation in seconds"]', flush=True)
    
    binfile = None
    timelimit = 60
    print(len(sys.argv))
    if len(sys.argv) < 2:
        raise SystemExit("Please specifiy a .py file as argument.")
    elif len(sys.argv) > 2 and not sys.argv[2].startswith("-"):
        raise SystemExit("Invalid parameter after script. \n Possible options: \n -b \"binary input file\", \n -t \"time for generation in seconds\"")


    opts, args = getopt.getopt(sys.argv[2:], "b:t:")
    for opt, a in opts:
        if opt == "-b":
            print("Using binary file:", a, flush=True)
            binfile = a
        elif opt == "-t":
            timelimit = int(a)

    main([sys.argv[0],sys.argv[1],binfile,timelimit])