import { Component, OnInit } from '@angular/core';

@Component({
  selector: 'app-scoreboard',
  templateUrl: './scoreboard.component.html',
  styleUrls: ['./scoreboard.component.css'],
})
export class ScoreboardComponent implements OnInit {
  users = ['Mahesh', 'Shubra', 'Jaydip'];

  constructor() {}

  ngOnInit() {}
}
