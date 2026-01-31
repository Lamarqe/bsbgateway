#!/bin/sh

# Path to venv and python
VENV_DIR=".venv"
PYTHON_BIN="$VENV_DIR/bin/python3"

# If venv directory does not exist, offer to create it
if [ ! -d "$VENV_DIR" ]; then
    echo "Virtual environment '$VENV_DIR' not found."
    echo "Create it now? [Y/n]: "
    # shellcheck disable=SC2039  # 'read -r' is POSIX in most /bin/sh implementations
    read ans
    case "$ans" in
        [nN]*)
            exit 1
            ;;
    esac
    printf "\n*** Creating environment '$VENV_DIR'...\n"
    # Create virtual environment
    if command -v python3 >/dev/null 2>&1; then
        python3 -m venv "$VENV_DIR" || {
            echo "Failed to create virtual environment in '$VENV_DIR'."
            exit 1
        }
    else
        echo "python3 not found in PATH."
        exit 1
    fi
    
    printf "\n*** Installing bsbgateway in editable mode\n"
    # .. this also installs all dependecies
    "$PYTHON_BIN" -m pip install -e .

    printf "\n*** Starting BsbGateway\n"
fi

# Run the app
$VENV_DIR/bin/bsbgateway manage $*
    