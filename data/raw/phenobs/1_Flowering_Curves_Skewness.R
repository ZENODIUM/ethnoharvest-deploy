#Remove all objects
rm(list=ls(all=TRUE))

#Load needed Packages
library(dplyr)
library(moments) 

#Data preparation####

#Select the data directory where you saved the raw data files.
data_dir <- choose.dir()

#Load phenology raw data (2019-2023)
d2019 <-read.table(file.path(data_dir, "rawdata_PhenObs_2019.csv"), sep=";",header=T ,fill=TRUE)
d2019$Year <- c(2019)
d2020 <-read.table(file.path(data_dir, "rawdata_PhenObs_2020.csv"), sep=";",header=T ,fill=TRUE)
d2020$Year <- c(2020)
d2021 <-read.table(file.path(data_dir, "rawdata_PhenObs_2021.csv"), sep=";",header=T ,fill=TRUE)
d2021$Year <- c(2021)
d2022 <-read.table(file.path(data_dir, "rawdata_PhenObs_2022.csv"), sep=";",header=T ,fill=TRUE)
d2022$Year <- c(2022)
d2023 <-read.table(file.path(data_dir, "rawdata_PhenObs_2023.csv"), sep=";",header=T ,fill=TRUE)
d2023$Year <- c(2023)

#Combine the different years into one dataset
phen<-rbind(d2019,d2020,d2021,d2022,d2023) 

#Add an identifier with Species_ID and Year
phen$Ident <-paste(phen$Species_ID, phen$Year, sep="_") #Add an identifier with Species_ID and Year

#Delete NAs from the column "Flowering.Intensity"
phen <- phen[!(is.na(phen$Flowering.intensity)), ]

#Subset for only observations with more than 24 weeks of monitoring
number_yes <- phen %>% group_by(Ident) %>% summarise(number_yes= length(Botanic_Garden))
phen <-merge(phen,number_yes, by=c("Ident"))
phen<-phen %>% filter(number_yes >24)

#Calculation of the skewness####

#Preparation of an empty data frame
output1 <- data.frame(skewness=NA,Species_ID=NA, Species=NA, Botanic_Garden=NA,Year=NA,Ident=NA)

#Vector of all Ident (Species monitored in one year in one garden)
Ident<-phen$Ident %>% unique()

#For loop across all annual records of a species within a garden
for (i in Ident)
{
  phen_sub<- phen %>% filter(Ident == (i)) #Subset corresponding to Ident 
  abs <- phen_sub$Flowering.intensity #Creating a vector with flowering.intensity
  times<- phen_sub$Doy #Creating a vector with the DOYs
  abs_expand <- rep(times, times=round(abs)) #From relative values to a genuine numerical distribution
  skewness<-skewness(abs_expand) #Calculation of the skewness
  d <- as.data.frame(cbind(skewness)) #Creating a data frame
  d$Species_ID <- phen_sub[1,4] #Adding Species_ID to the data frame
  d$Species <- phen_sub[1,2] #Adding Species to the data frame
  d$Botanic_Garden <- phen_sub[1,3] #Adding Botanic Garden to the data frame
  d$Year<-phen_sub[1,16] #Adding Year to the data frame
  d$Ident <- i #Adding Ident to the data frame
  output1<-rbind(output1,d) #Binding the results with the empty data frame for the data output
}

#Delete annual records with skewness=NA or NaN
skweness_data <- output1[!(is.na(output1$skewness)), ]

#Saving the data set####
write.table(skweness_data, file = file.path(data_dir, "Skweness_Overview.csv"), sep=";",dec = ".", row.names = FALSE)
