# create a dummy git repository to fetch tags from the kernel git repository
mkdir git 2> /dev/null

# it is already there
if [ $? -eq 1 ]; then
    echo "Already initialized"
    exit;
else
    f="DO_NOT_DELETE_THIS_DIRECTORY.txt"
    echo "Do not delete this directory." >> git/${f}
    echo "It is used to fetch the latest tags from https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git" >> git/${f}
    echo "Try 'git ls-remote --tags --refs' to see what this means." >> git/${f}
fi

cd git
git init
git remote add origin https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git
echo "Done"
