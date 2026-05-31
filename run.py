import os
import sys
import traceback

print("STEP 1: run.py started", flush=True)

try:
    from app import create_app
    print("STEP 2: imported create_app successfully", flush=True)

    app = create_app()
    print("STEP 3: app created successfully", flush=True)

except Exception as e:
    print("FATAL ERROR DURING APP STARTUP:", flush=True)
    print(str(e), flush=True)
    traceback.print_exc()
    sys.exit(1)

if __name__ == "__main__":
    try:
        port = int(os.environ.get("PORT", 10000))
        print(f"STEP 4: starting Flask on port {port}", flush=True)
        app.run(host="0.0.0.0", port=port, debug=False)
    except Exception as e:
        print("FATAL ERROR DURING app.run():", flush=True)
        print(str(e), flush=True)
        traceback.print_exc()
        sys.exit(1)
