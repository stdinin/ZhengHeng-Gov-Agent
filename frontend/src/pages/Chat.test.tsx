import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, vi } from 'vitest'
import { sendChat } from '../api/client'
import { Chat } from './Chat'
import type { ChatResponse } from '../types/api'

vi.mock('../Session', () => ({ useSession: () => ({ user: { id: 'test-user', email: 'test@example.local', role: 'USER' } }) }))
vi.mock('../api/client', () => ({ sendChat: vi.fn() }))
afterEach(() => vi.mocked(sendChat).mockReset())
const answer: ChatResponse = { trace_id: 'record-1', session_id: 'session-1', status: 'SUCCESS', answer: '测试答复正文', attempts: 1, warnings: [], citations: [{ id: 'C1', chunk_id: 'chunk-1', title: '测试政策', department: 'tax', status: 'ACTIVE', excerpt: '测试依据', source_url: 'javascript:alert(1)' }] }

it('rejects whitespace-only questions and never sends them', async () => {
  render(<Chat />)
  fireEvent.change(screen.getByRole('textbox', { name: '事项描述' }), { target: { value: '   ' } })
  fireEvent.click(screen.getByRole('button', { name: '提交咨询' }))
  expect(await screen.findByText('请输入具体咨询事项。')).toBeInTheDocument()
  expect(sendChat).not.toHaveBeenCalled()
})
it('hides an old answer during a new request and prevents duplicate submissions', async () => {
  vi.mocked(sendChat).mockResolvedValueOnce(answer)
  render(<Chat />)
  const input = screen.getByRole('textbox', { name: '事项描述' })
  fireEvent.change(input, { target: { value: '第一个事项' } })
  fireEvent.click(screen.getByRole('button', { name: '提交咨询' }))
  expect(await screen.findByText('测试答复正文')).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: /查看政策原文/ })).not.toBeInTheDocument()
  expect(screen.getByRole('link', { name: /查看办理记录/ })).toHaveAttribute('href', '#/trace?id=record-1')
  let reject!: (reason: Error) => void
  vi.mocked(sendChat).mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail }))
  fireEvent.change(input, { target: { value: '第二个事项' } })
  fireEvent.click(screen.getByRole('button', { name: '提交咨询' }))
  await waitFor(() => expect(sendChat).toHaveBeenCalledTimes(2))
  expect(screen.queryByText('测试答复正文')).not.toBeInTheDocument()
  expect(input).toBeDisabled()
  await act(async () => { reject(new Error('网络暂时不可用')) })
  expect(await screen.findByText('本次咨询未完成')).toBeInTheDocument()
  expect(input).toHaveValue('第二个事项')
  expect(sendChat).toHaveBeenLastCalledWith('第二个事项', 'session-1', expect.any(AbortSignal))
})
