#!/bin/bash
echo "=== SWOT Dashboard Setup ==="
echo

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 is not installed."
    echo "Install it with your package manager:"
    echo "  Ubuntu/Debian: sudo apt install python3 python3-venv python3-pip"
    echo "  macOS: brew install python3"
    exit 1
fi

echo "Found Python:"
python3 --version
echo

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    echo
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "Installing dependencies (this may take a few minutes)..."
python -m pip install -r requirements.txt
echo

# Launch the dashboard
echo
echo "=== Setup complete! Launching dashboard... ==="
echo
echo "The dashboard will open at http://localhost:8501"
echo "Press Ctrl+C to stop it."
echo
streamlit run dashboard_swot.py
