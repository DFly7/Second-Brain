import { toast as sonner } from 'sonner'

export const toast = {
  success: (msg: string) => sonner.success(msg),
  error: (msg: string) => sonner.error(msg),
  info: (msg: string) => sonner.info(msg),
}
