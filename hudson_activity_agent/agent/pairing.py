"""First-run pairing window (tkinter, part of the standard library)."""

NOTICE = ("This app records your active and idle time and the applications you use "
          "during work, and sends them to your company's Odoo. A coloured icon in the "
          "system tray shows while tracking is running.")


def run_pairing_dialog(initial_url, attempt) -> bool:
    """attempt(url, code) -> error message or None. Returns True when paired."""
    import tkinter as tk
    from tkinter import ttk

    result = {"ok": False}
    root = tk.Tk()
    root.title("Hudson Activity - Pair this device")
    root.resizable(False, False)

    frame = ttk.Frame(root, padding=16)
    frame.grid(sticky="nsew")

    ttk.Label(frame, text="Pair this computer with Odoo", font=("TkDefaultFont", 12, "bold")).grid(
        row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
    ttk.Label(frame, text=NOTICE, wraplength=380, justify="left").grid(
        row=1, column=0, columnspan=2, sticky="w", pady=(0, 12))

    ttk.Label(frame, text="Server URL").grid(row=2, column=0, sticky="w")
    url_var = tk.StringVar(value=initial_url or "https://")
    url_entry = ttk.Entry(frame, textvariable=url_var, width=40)
    url_entry.grid(row=2, column=1, sticky="ew", pady=2)

    ttk.Label(frame, text="Pairing code").grid(row=3, column=0, sticky="w")
    code_var = tk.StringVar()
    code_entry = ttk.Entry(frame, textvariable=code_var, width=40)
    code_entry.grid(row=3, column=1, sticky="ew", pady=2)

    ttk.Label(frame, text="Ask your administrator for the pairing code (Odoo > Employees).",
              foreground="#666").grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))
    error_var = tk.StringVar()
    ttk.Label(frame, textvariable=error_var, foreground="#c0392b", wraplength=380).grid(
        row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))

    buttons = ttk.Frame(frame)
    buttons.grid(row=6, column=0, columnspan=2, sticky="e", pady=(12, 0))

    def do_pair(_event=None):
        url, code = url_var.get().strip(), code_var.get().strip()
        if not url or not code:
            error_var.set("Please enter both the server URL and the pairing code.")
            return
        pair_btn.state(["disabled"])
        error_var.set("Connecting...")
        root.update_idletasks()
        error = attempt(url, code)
        if error:
            error_var.set(error)
            pair_btn.state(["!disabled"])
        else:
            result["ok"] = True
            root.destroy()

    pair_btn = ttk.Button(buttons, text="Pair", command=do_pair)
    pair_btn.grid(row=0, column=1, padx=(6, 0))
    ttk.Button(buttons, text="Cancel", command=root.destroy).grid(row=0, column=0)

    root.bind("<Return>", do_pair)
    (code_entry if initial_url else url_entry).focus_set()
    root.eval("tk::PlaceWindow . center")
    root.mainloop()
    return result["ok"]
