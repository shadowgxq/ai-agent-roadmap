import type { ButtonHTMLAttributes, InputHTMLAttributes, TextareaHTMLAttributes } from 'react';
import styles from '../../SupportPage.module.css';

export function SupportButton({
  className,
  type = 'button',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button type={type} className={`${styles.button} ${className ?? ''}`} {...props} />;
}
export function SupportInput({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={`${styles.input} ${className ?? ''}`} {...props} />;
}
export function SupportTextarea({
  className,
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={`${styles.input} ${className ?? ''}`} {...props} />;
}
