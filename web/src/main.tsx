import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import { PhoneApp } from './PhoneApp'
import { VoiceApp } from './voice/VoiceApp'
import { RoomView } from './RoomView'
import { DevPanel } from './dev/DevPanel'
import { devMode } from './ws'

const classic = new URLSearchParams(location.search).has('classic')
const isRoom = location.pathname.replace(/\/$/, '').endsWith('/room')

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {isRoom ? <RoomView /> : classic ? <PhoneApp /> : <VoiceApp />}
    {devMode && <DevPanel />}
  </StrictMode>,
)
