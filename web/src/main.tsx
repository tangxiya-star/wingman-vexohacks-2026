import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import { PhoneApp } from './PhoneApp'
import { RoomView } from './RoomView'
import { DevPanel } from './dev/DevPanel'
import { devMode } from './ws'

const isRoom = location.pathname.replace(/\/$/, '').endsWith('/room')

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {isRoom ? <RoomView /> : <PhoneApp />}
    {devMode && <DevPanel />}
  </StrictMode>,
)
