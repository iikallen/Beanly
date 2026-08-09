"use client";

import { type InputHTMLAttributes, useId, useState } from "react";

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, "id"> & {
  label: string;
};

export function FormField({ label, type = "text", ...props }: Props) {
  const id = useId();
  const [visible, setVisible] = useState(false);
  const password = type === "password";

  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <div className="input-wrap">
        <input id={id} type={password && visible ? "text" : type} {...props} />
        {password && (
          <button
            className="password-toggle"
            type="button"
            onClick={() => setVisible((value) => !value)}
            aria-label={visible ? "Hide password" : "Show password"}
          >
            <svg aria-hidden="true" viewBox="0 0 24 24">
              <path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z" />
              <circle cx="12" cy="12" r="2.5" />
            </svg>
          </button>
        )}
      </div>
    </div>
  );
}
