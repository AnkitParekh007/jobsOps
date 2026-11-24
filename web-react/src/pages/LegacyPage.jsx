import React from 'react';
import LegacyMarkup from '../components/LegacyMarkup.jsx';
import {sections} from '../data/legacyContent.js';
export default function LegacyPage({name}){return <LegacyMarkup html={sections[name]}/>;}
